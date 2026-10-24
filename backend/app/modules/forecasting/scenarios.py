"""Сценарии преобразуют только будущие компоненты; исходный DTO не меняется."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.modules.contracts import ForecastInput, PlannedEventDTO, RecurrenceGroup


@dataclass(frozen=True)
class ScenarioState:
    events: list[PlannedEventDTO]
    extra_expenses: dict[date, int]
    inflow_factor: float
    recurring_factors: dict[str, float]
    explanations: list[dict]


def apply_scenario(data: ForecastInput, groups: list[RecurrenceGroup]) -> ScenarioState:
    events = {event.id: event for event in data.planned_events if event.available_at <= data.as_of}
    factors = {group.group_id: 1.0 for group in groups}
    extra = {}
    inflow = 1.0
    explanations = []
    end = data.as_of + timedelta(days=data.horizon_days)
    for change in data.scenario:
        if change.kind == "delay_event":
            if change.target_id not in events or not isinstance(change.shift_days, int) or change.shift_days < 0:
                raise ValueError("delay_event требует известный event и неотрицательные shift_days")
            event = events[change.target_id]
            if event.status not in {"planned", "partially_paid"} or event.remaining_amount_minor <= 0:
                raise ValueError("Нельзя переносить закрытое событие")
            events[event.id] = replace(event, due_date=event.due_date + timedelta(days=change.shift_days))
        elif change.kind == "reduce_irregular_inflow":
            if change.factor is None or not math.isfinite(change.factor) or not 0 <= change.factor <= 1:
                raise ValueError("reduce_irregular_inflow требует factor от0 до1")
            inflow *= change.factor
        elif change.kind == "increase_recurring":
            if change.factor is None or not math.isfinite(change.factor) or change.factor < 1:
                raise ValueError("increase_recurring требует конечный factor >=1")
            targets = [change.target_id] if change.target_id is not None else list(factors)
            if any(target not in factors for target in targets) or not targets:
                raise ValueError("Не найдена регулярность сценария")
            for target in targets:
                factors[target] *= change.factor
        elif change.kind == "add_expense":
            if (
                not isinstance(change.amount_minor, int)
                or change.amount_minor <= 0
                or change.on_date is None
                or not data.as_of < change.on_date <= end
            ):
                raise ValueError("add_expense требует положительную сумму и дату внутри горизонта")
            extra[change.on_date] = extra.get(change.on_date, 0) + change.amount_minor
        else:
            raise ValueError("Неизвестный вид сценария")
        explanations.append(
            {"kind": "scenario", "label": change.kind, "source_ref": change.target_id, "detail": {"hypothetical": True}}
        )
    # Direction импортируется здесь в модели, чтобы значения enum не попали в JSON.
    return ScenarioState(list(events.values()), extra, inflow, factors, explanations)
