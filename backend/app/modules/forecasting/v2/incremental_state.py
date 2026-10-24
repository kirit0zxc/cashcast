"""Версионированный checkpoint для дельты фактов и календаря одного счёта."""

import hashlib
import json

from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import ForecastInput
from app.modules.forecasting.v2.legacy_limits import MAX_LEGACY_WORK
from app.modules.forecasting.v2.quality import ForecastInputError

STATE_KEY = "_incremental_state"
STATE_VERSION = "ledger-update-v2"


class IncrementalState:
    @staticmethod
    def fingerprint(data: ForecastInput) -> str:
        raw = ForecastInputCodec.encode(data)["input"]
        # Версия всего снимка меняется вместе с календарём, её не включаем в ключ истории.
        raw.pop("planned_events")
        raw.pop("data_version")
        return IncrementalState.digest(raw)

    @staticmethod
    def digest(value: dict) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    @classmethod
    def pack(cls, data: ForecastInput, prepared: dict) -> dict:
        return {
            "version": STATE_VERSION,
            "fingerprint": cls.fingerprint(data),
            "context": {
                "account_id": data.account_id,
                "as_of": data.as_of.isoformat(),
                "horizon_days": data.horizon_days,
                "seed": data.seed,
            },
            "digest": cls.digest(prepared),
            "prepared": prepared,
        }

    @classmethod
    def unpack(cls, data: ForecastInput, state: dict | None) -> dict | None:
        try:
            return cls._unpack(data, state)
        except (AttributeError, KeyError, TypeError, ValueError, IndexError):
            # Повреждённая структура служебного JSON не делает исходные финансовые данные ошибочными.
            return None

    @classmethod
    def _unpack(cls, data: ForecastInput, state: dict | None) -> dict | None:
        if data.scenario or not isinstance(state, dict):
            return None
        if state.get("version") != STATE_VERSION:
            return None
        fingerprint = state.get("fingerprint")
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)
        ):
            return None
        context = state.get("context", {})
        if not isinstance(context, dict):
            return None
        if (
            context.get("account_id") != data.account_id
            or context.get("seed") != data.seed
            or context.get("horizon_days") != data.horizon_days
            or not isinstance(context.get("as_of"), str)
            or context["as_of"] > data.as_of.isoformat()
        ):
            return None
        prepared = state.get("prepared")
        # Старые/повреждённые checkpoints не мешают штатному полному расчёту.
        if not isinstance(prepared, dict) or state.get("digest") != cls.digest(prepared):
            return None
        if (
            not {
                "history",
                "groups_snapshot",
                "days",
                "warnings",
                "reliable",
                "excluded_count",
                "weekday",
                "residual_paths",
                "sampling_grid",
                "sampling_key",
                "opening",
            }
            <= prepared.keys()
        ):
            return None
        if len(prepared["residual_paths"]) != data.horizon_days or len(prepared["days"]) > 84:
            return None
        if prepared["reliable"]:
            grid = prepared["sampling_grid"]
            if (
                len(grid) != data.horizon_days
                or any(
                    len(row) != 200 or any(type(i) is not int or not 0 <= i < len(prepared["days"]) for i in row)
                    for row in grid
                )
                or any(len(row) != 200 for row in prepared["residual_paths"])
            ):
                return None
        return prepared

    @staticmethod
    def check_schedule_budget(data: ForecastInput, prepared: dict) -> None:
        # Новые планы могут резко увеличить стоимость сопоставления: guard сохраняется.
        groups = prepared["groups_snapshot"]["input"]["recurrences"]
        members = sum(len(group["member_transaction_ids"]) for group in groups)
        history_work = len(data.daily_balances) * len({txn.booked_on for txn in data.txns})
        work = history_work + len(data.txns) * (members + len(groups))
        work += len(data.planned_events) * (data.horizon_days // 7 + 2) * members
        if len(groups) > 500 or work > MAX_LEGACY_WORK:
            raise ForecastInputError("forecast_resource_limit", "Превышен бюджет обновления календаря")
