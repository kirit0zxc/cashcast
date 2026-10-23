"""Baseline-прогноз «повтор последней недели» — заглушка интегратора, НЕ финальная модель.

Владелец финальной модели — Данил (modules/forecasting/). Этот baseline существует,
чтобы сквозной путь CSV → БД → прогноз → JSON работал с первого часа и чтобы у Данила
был честный ориентир для сравнения («baseline показан, даже если он победил»).

Что делает: берёт средний дневной приток и отток за последние 7 дней до as_of и
повторяет их на горизонт, добавляя подтверждённые плановые события в их даты.
Неопределённость не оценивает: p10=p50=p90, probability_negative=None, risk.available=False.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.modules.contracts import (
    Direction,
    ForecastInput,
    ForecastPointDTO,
    ForecastResult,
    RiskSummary,
)

MODEL_VERSION = "baseline-repeat-week-0.1"
_LOOKBACK_DAYS = 7


class BaselineForecastService:
    """Реализует протокол ForecastService. Детерминирован: один вход → один результат."""

    def run(self, data: ForecastInput) -> ForecastResult:
        assumptions: list[str] = [
            "Baseline: средний приток и отток за последние 7 дней повторяются ежедневно.",
            "Это опорная модель для сравнения, а не итоговый прогноз.",
        ]
        warnings: list[str] = []

        window_start = data.as_of - timedelta(days=_LOOKBACK_DAYS)
        recent = [t for t in data.txns if window_start < t.booked_on <= data.as_of]
        if not recent:
            warnings.append("Нет операций за последнюю неделю до даты среза: потоки приняты нулевыми.")

        in_sum = sum(t.amount_minor for t in recent if t.direction == Direction.IN)
        out_sum = sum(t.amount_minor for t in recent if t.direction == Direction.OUT)
        avg_in = in_sum // _LOOKBACK_DAYS
        avg_out = out_sum // _LOOKBACK_DAYS

        # Подтверждённые будущие события раскладываем по датам. Остаток обязательства,
        # а не полная сумма: частично оплаченное не считаем второй раз.
        planned_in: dict[date, int] = defaultdict(int)
        planned_out: dict[date, int] = defaultdict(int)
        for ev in data.planned_events:
            if ev.status in {"paid", "cancelled"} or ev.remaining_amount_minor <= 0:
                continue
            bucket = planned_in if ev.direction == Direction.IN else planned_out
            bucket[ev.due_date] += ev.remaining_amount_minor

        points: list[ForecastPointDTO] = []
        balance = data.opening_balance_minor
        first_negative: date | None = None
        max_deficit = 0
        for offset in range(1, data.horizon_days + 1):
            day = data.as_of + timedelta(days=offset)
            inflow = avg_in + planned_in.get(day, 0)
            outflow = avg_out + planned_out.get(day, 0)
            balance = balance + inflow - outflow
            if balance < 0:
                if first_negative is None:
                    first_negative = day
                max_deficit = max(max_deficit, -balance)
            points.append(
                ForecastPointDTO(
                    point_date=day,
                    inflow_minor=inflow,
                    outflow_minor=outflow,
                    # Без оценки неопределённости три квантиля совпадают.
                    balance_p10_minor=balance,
                    balance_p50_minor=balance,
                    balance_p90_minor=balance,
                    probability_negative=None,
                )
            )

        # Риск baseline считает детерминированно (есть минус или нет), без вероятности.
        risk = RiskSummary(
            available=False,
            first_negative_date=first_negative,
            max_deficit_minor=max_deficit if first_negative else None,
            probability_any_negative=None,
        )
        warnings.append("Оценка вероятности разрыва недоступна в baseline (нет бутстрапа траекторий).")

        return ForecastResult(
            model_version=MODEL_VERSION,
            points=points,
            risk=risk,
            assumptions=assumptions,
            data_warnings=warnings,
            details={"method": "baseline", "avg_in_minor": avg_in, "avg_out_minor": avg_out},
        )
