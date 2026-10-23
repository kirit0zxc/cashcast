"""Заранее заданные исследовательские альтернативы; не переключают фабрику продукта."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from statistics import mean

from app.modules.categorization.service import get_categorizer
from app.modules.contracts import Direction, ForecastInput, ForecastPointDTO, ForecastResult, RiskSummary
from app.modules.forecasting.legacy_v1.seasonal import _money, _quantile
from app.modules.forecasting.seasonal import _recurring_history_ids, _schedule
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR, ForecastInputError, assess_quality, validate_input
from app.modules.planning.service import get_recurrence_detector

METHODS = ("mean", "ewm", "winsor", "trend")


def _upper_quantile(values: list[int], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _weighted(values, weights):
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights) if weights else 0.0


class ExperimentalForecastService:
    """Версия исследовательского метода, всегда явно отличная от production1.0."""

    def __init__(self, method: str, paths: int = 200):
        if method not in METHODS:
            raise ValueError("Неизвестный исследовательский метод")
        if type(paths) is not int or not 20 <= paths <= 500:
            raise ValueError("Число траекторий20–500")
        self.method, self.paths = method, paths

    @property
    def model_version(self):
        return f"research-weekday-{self.method}-2.0-w84-p{self.paths}"

    def run(self, data: ForecastInput) -> ForecastResult:
        data = validate_input(data)
        quality = assess_quality(data)
        assignments = get_categorizer().categorize(data.txns)
        txns = [
            replace(txn, category=assignment.category.value, direction=Direction(txn.direction))
            for txn, assignment in zip(data.txns, assignments, strict=True)
        ]
        recurrence_txns = (
            [txn for txn in txns if txn.booked_on >= quality.training_start] if quality.reconciliation_breaks else txns
        )
        groups = get_recurrence_detector().detect(recurrence_txns, data.as_of)
        work = len(txns) * len(groups) + len(data.planned_events) * len(groups) * (data.horizon_days // 7 + 1) * 6
        if len(groups) > 500 or work > 5_000_000:
            raise ForecastInputError("forecast_resource_limit", "Превышен бюджет сопоставления регулярностей")
        clean = replace(
            data,
            txns=txns,
            planned_events=[replace(event, direction=Direction(event.direction)) for event in data.planned_events],
        )
        try:
            state, schedule = _schedule(clean, groups)
        except (ValueError, OverflowError) as error:
            raise ForecastInputError(
                "invalid_scenario", "Некорректные параметры или календарная граница сценария"
            ) from error
        for _day, _direction, amount, _kind, _ref in schedule:
            if type(amount) is not int or not 0 <= amount <= MAX_MONEY_MINOR:
                raise ForecastInputError("forecast_resource_limit", "Сценарий превышает денежный бюджет")
        excluded = _recurring_history_ids(groups, recurrence_txns)
        days = [quality.training_start + timedelta(days=index) for index in range(quality.history_days)]
        residual = defaultdict(lambda: [0, 0])
        for txn in txns:
            if txn.id not in excluded and quality.training_start <= txn.booked_on <= data.as_of:
                residual[txn.booked_on][0 if txn.direction == Direction.IN else 1] += txn.amount_minor
        caps = {}
        for weekday in range(7):
            for direction in range(2):
                values = [residual[day][direction] for day in days if day.weekday() == weekday]
                caps[weekday, direction] = _upper_quantile(values, 0.95)
        modeled = {}
        clipped = 0
        for day in days:
            modeled[day] = []
            for direction in range(2):
                value = residual[day][direction]
                if self.method == "winsor":
                    clipped += value > caps[day.weekday(), direction]
                    value = _money(min(value, caps[day.weekday(), direction]))
                modeled[day].append(value)
        trend = [1.0, 1.0]
        if self.method == "trend" and len(days) >= 56:
            for direction in range(2):
                recent = mean(modeled[day][direction] for day in days[-28:])
                previous = mean(modeled[day][direction] for day in days[-56:-28])
                ratio = recent / previous if previous > 0 else 1.0
                trend[direction] = min(1.25, max(0.75, 1 + 0.25 * (ratio - 1)))
        expected = {}
        for weekday in range(7):
            selected = [day for day in days if day.weekday() == weekday]
            weights = [2 ** (-(data.as_of - day).days / 28) if self.method == "ewm" else 1.0 for day in selected]
            expected[weekday] = [
                _weighted([modeled[day][direction] for day in selected], weights) * trend[direction]
                for direction in range(2)
            ]
        known = defaultdict(lambda: [0, 0])
        component = defaultdict(lambda: defaultdict(int))
        for day, direction, amount, kind, _ref in schedule:
            index = 0 if direction == Direction.IN else 1
            known[day][index] += amount
            component[day][f"{kind}_{'in' if index == 0 else 'out'}_minor"] += amount
        future = [data.as_of + timedelta(days=index) for index in range(1, data.horizon_days + 1)]
        trajectories = [[] for _ in future]
        negative_any = 0
        starts = {
            weekday: [index for index, day in enumerate(days) if day.weekday() == weekday and index + 6 < len(days)]
            for weekday in range(7)
        }
        if quality.eligible_for_simulation:
            for path in range(self.paths):
                # Отдельный поток каждого path сохраняет парность и prefix при смене горизонта.
                rng = random.Random(f"{data.seed}:{path}")  # noqa: S311
                balance, ever_negative, block_start = data.opening_balance_minor, False, 0
                for index, day in enumerate(future):
                    if index % 7 == 0:
                        options = starts[day.weekday()]
                        weights = [
                            2 ** (-(data.as_of - days[start + 6]).days / 28) if self.method == "ewm" else 1.0
                            for start in options
                        ]
                        block_start = rng.choices(options, weights=weights, k=1)[0]
                    incoming, outgoing = modeled[days[block_start + index % 7]]
                    incoming = _money(incoming * trend[0] * state.inflow_factor)
                    outgoing = _money(outgoing * trend[1])
                    balance += incoming - outgoing + known[day][0] - known[day][1]
                    trajectories[index].append(balance)
                    ever_negative |= balance < 0
                negative_any += ever_negative
        points = []
        balance = data.opening_balance_minor
        daily_components = []
        for index, day in enumerate(future):
            irregular_in = _money(expected[day.weekday()][0] * state.inflow_factor)
            irregular_out = _money(expected[day.weekday()][1])
            incoming, outgoing = irregular_in + known[day][0], irregular_out + known[day][1]
            if max(incoming, outgoing) > MAX_MONEY_MINOR:
                raise ForecastInputError("forecast_resource_limit", "Поток превышает денежный бюджет")
            balance += incoming - outgoing
            values = trajectories[index] if quality.eligible_for_simulation else [balance]
            daily_probability = (
                sum(value < 0 for value in values) / self.paths if quality.eligible_for_simulation else None
            )
            points.append(
                ForecastPointDTO(
                    day,
                    incoming,
                    outgoing,
                    _quantile(values, 0.1),
                    _quantile(values, 0.5),
                    _quantile(values, 0.9),
                    daily_probability,
                )
            )
            daily_components.append(
                {
                    "date": day.isoformat(),
                    "irregular_in_minor": irregular_in,
                    "irregular_out_minor": irregular_out,
                    "known_in_minor": known[day][0],
                    "known_out_minor": known[day][1],
                    **dict(component[day]),
                }
            )
        negatives = [point for point in points if point.balance_p50_minor < 0]
        minimum = min(points, key=lambda point: point.balance_p50_minor)
        related = sorted(
            {
                ref
                for day, direction, _, kind, ref in schedule
                if kind == "planned" and ref and direction == Direction.OUT and day <= minimum.point_date
            }
        )
        risk = RiskSummary(
            quality.eligible_for_simulation,
            negatives[0].point_date if negatives else None,
            max(-point.balance_p50_minor for point in negatives) if negatives else None,
            negative_any / self.paths if quality.eligible_for_simulation else None,
            related if negatives else [],
        )
        explanations = list(state.explanations)
        for day, direction, amount, kind, ref in schedule:
            explanations.append(
                {
                    "kind": kind,
                    "label": "Подтверждённый компонент ожидаемого потока",
                    "amount_minor": amount,
                    "source_ref": ref,
                    "detail": {"date": day.isoformat(), "direction": direction.value},
                }
            )
        explanations.append(
            {
                "kind": "risk_minimum",
                "label": "Минимум медианного остатка",
                "amount_minor": minimum.balance_p50_minor,
                "detail": {
                    "date": minimum.point_date.isoformat(),
                    "related_event_ids": related,
                    "causal_guarantee": False,
                },
            }
        )
        return ForecastResult(
            self.model_version,
            points,
            risk,
            [
                "Исследовательская версия по заранее зафиксированной сетке; не продуктовый default.",
                "Вероятности здесь raw model scores для калибровочного эксперимента, не подтверждённая вероятность.",
                "Ненаблюдаемые дни условно нулевые; реальные суммы/история не исправляются.",
                "Квантили траекторий отличаются от накопленных средних потоков.",
            ],
            list(quality.warnings),
            {
                "method": self.method,
                "summary": "Исследовательский расчёт ожидаемых компонентов и риска.",
                "quality": quality.to_dict(),
                "explanations": explanations,
                "daily_components": daily_components,
                "paths": self.paths if quality.eligible_for_simulation else 0,
                "clipped_model_days": clipped,
                "trend_factors": trend,
                "recurrence_count": len(groups),
                "recurrence_ids": [group.group_id for group in groups],
                "raw_probability_research_only": True,
            },
        )
