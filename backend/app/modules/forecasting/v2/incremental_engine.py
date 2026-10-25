"""Переиспользование истории и bootstrap при изменении календаря; математика frozen1.0."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import timedelta

from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import Direction, ForecastInput, ForecastPointDTO, ForecastResult, RiskSummary
from app.modules.forecasting.legacy_v1.seasonal import (
    MODEL_VERSION,
    _money,
    _quantile,
    _schedule,
)
from app.modules.forecasting.v2.incremental_history import IncrementalHistory
from app.modules.forecasting.v2.incremental_paths import IncrementalPaths


class IncrementalSeasonalService:
    def __init__(self, paths: int = 200, lookback_days: int = 84):
        if not 20 <= paths <= 2000:
            raise ValueError("Число траекторий должно быть20–2000")
        self.paths = paths
        if lookback_days != 84:
            raise ValueError("Инкрементальная модель использует окно84дня")
        self.lookback_days = lookback_days

    @property
    def model_version(self) -> str:
        """Публичная версия для фиксации модели в очереди и сценарном снимке."""
        return f"{MODEL_VERSION}-w{self.lookback_days}"

    def run(self, data: ForecastInput, prepared: dict | None = None) -> ForecastResult:
        if not 1 <= data.horizon_days <= 366:
            raise ValueError("Горизонт должен быть1–366 дней")
        history = IncrementalHistory()
        txns, groups, days, warnings, reliable, excluded_count, weekday, residual = history.prepare(data, prepared)
        clean = replace(data, txns=txns)
        state, schedule = _schedule(clean, groups)
        fixed = defaultdict(lambda: [0, 0])
        for day, direction, amount, _kind, _ref in schedule:
            fixed[day][0 if direction == Direction.IN else 1] += amount
        future = [data.as_of + timedelta(days=offset) for offset in range(1, data.horizon_days + 1)]
        sampler = IncrementalPaths(self.paths)
        residual_paths = sampler.update(data, days, future, reliable, residual, prepared)
        trajectories = [[] for _ in future]
        cumulative = 0
        for index, day in enumerate(future):
            cumulative += fixed[day][0] - fixed[day][1]
            trajectories[index] = [value + cumulative for value in residual_paths[index]]
        negative_any = sum(any(day[path] < 0 for day in trajectories) for path in range(self.paths)) if reliable else 0
        self.metrics = {**history.metrics, **sampler.metrics}
        # В JSONB сохраняем только внутреннее состояние, оно не входит в публичный ответ API.
        self.prepared = {
            "history": history.state, **sampler.state,
            "groups_snapshot": ForecastInputCodec.encode(replace(
                data, txns=[], daily_balances=[], planned_events=[], recurrences=groups, scenario=[],
            )),
            "days": [day.isoformat() for day in days], "warnings": warnings, "reliable": reliable,
            "excluded_count": excluded_count, "weekday": weekday, "residual_paths": residual_paths,
        }
        points = []
        balance = data.opening_balance_minor
        for index, day in enumerate(future):
            incoming = _money(weekday[day.weekday()][0] * state.inflow_factor) + fixed[day][0]
            outgoing = _money(weekday[day.weekday()][1]) + fixed[day][1]
            balance += incoming - outgoing
            values = trajectories[index] if reliable else [balance]
            points.append(
                ForecastPointDTO(
                    day,
                    incoming,
                    outgoing,
                    _quantile(values, 0.1),
                    _quantile(values, 0.5),
                    _quantile(values, 0.9),
                    sum(value < 0 for value in values) / self.paths if reliable else None,
                )
            )
        negative = [point for point in points if point.balance_p50_minor < 0]
        risk = RiskSummary(
            reliable,
            negative[0].point_date if negative else None,
            max(-point.balance_p50_minor for point in negative) if negative else None,
            negative_any / self.paths if reliable else None,
            sorted(
                {
                    ref
                    for day, direction, _, kind, ref in schedule
                    if direction == Direction.OUT and kind == "planned" and ref and day <= negative[0].point_date
                }
            )
            if negative
            else [],
        )
        explanations = list(state.explanations)
        for _day, direction, amount, kind, ref in schedule:
            explanations.append(
                {
                    "kind": kind,
                    "label": "Ожидаемое поступление" if direction == Direction.IN else "Ожидаемое списание",
                    "amount_minor": amount,
                    "source_ref": ref,
                    "detail": {"date": _day.isoformat(), "direction": direction.value},
                }
            )
        explanations.append(
            {
                "kind": "residual",
                "label": "Нерегулярный поток по дням недели",
                "detail": {"history_days": len(days), "excluded_recurring_operations": excluded_count},
            }
        )
        return ForecastResult(
            self.model_version,
            points,
            risk,
            [
                "Потоки одного наблюдаемого счёта RUB; переводы собственных средств влияют на остаток.",
                f"Средние по дням недели за последние{self.lookback_days} дня; регулярности вынесены отдельно.",
                "Парный bootstrap недель сохраняет связь притока и оттока; вероятности модельные и не калиброваны.",
                "Дни без операций считаются нулевыми только при допущении полноты выгрузки; несверки отмечены.",
                "p10/p50/p90 — квантили траекторий; inflow/outflow — ожидаемые потоки, не дельта p50.",
            ],
            warnings,
            {
                "method": "seasonal_block_bootstrap",
                "summary": "Модельный прогноз остатка и его компонентов.",
                "explanations": explanations,
                "paths": self.paths if reliable else 0,
                "history_days": len(days),
                "recurrence_count": len(groups),
                "recurrence_ids": [group.group_id for group in groups],
                "daily_components": [
                    {"date": day.isoformat(), "planned_in_minor": fixed[day][0], "planned_out_minor": fixed[day][1]}
                    for day in future
                ],
            },
        )
