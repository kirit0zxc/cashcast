"""Внутренний checkpoint: допускает изменение только плановых событий, не истории."""

import hashlib
import json

from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import ForecastInput
from app.modules.forecasting.v2.legacy_limits import MAX_LEGACY_WORK
from app.modules.forecasting.v2.quality import ForecastInputError

STATE_KEY = "_incremental_state"
STATE_VERSION = "calendar-update-v1"


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
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def pack(cls, data: ForecastInput, prepared: dict) -> dict:
        return {"version": STATE_VERSION, "fingerprint": cls.fingerprint(data),
                "digest": cls.digest(prepared), "prepared": prepared}

    @classmethod
    def unpack(cls, data: ForecastInput, state: dict | None) -> dict | None:
        if data.scenario or not isinstance(state, dict):
            return None
        if state.get("version") != STATE_VERSION or state.get("fingerprint") != cls.fingerprint(data):
            return None
        prepared = state.get("prepared")
        # Старые/повреждённые checkpoints не мешают штатному полному расчёту.
        if not isinstance(prepared, dict) or state.get("digest") != cls.digest(prepared):
            return None
        if not {"categories", "groups_snapshot", "days", "warnings", "reliable", "excluded_count",
                "weekday", "residual_paths"} <= prepared.keys():
            return None
        if len(prepared["residual_paths"]) != data.horizon_days:
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
