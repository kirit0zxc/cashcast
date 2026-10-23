"""Юнит-тесты baseline-прогноза: детерминизм, горизонт, учёт планового события, риск."""

from __future__ import annotations

from datetime import date

from app.modules.contracts import (
    Direction,
    ForecastInput,
    PlannedEventDTO,
    TxnDTO,
)
from app.modules.forecasting.baseline import BaselineForecastService


def _week_of_txns(as_of: date) -> list[TxnDTO]:
    # 7 дней: каждый день приток 1000.00 и отток 800.00 (в копейках).
    out = []
    for i in range(1, 8):
        d = date.fromordinal(as_of.toordinal() - i)
        out.append(TxnDTO(f"in{i}", "acc", d, 100000, Direction.IN))
        out.append(TxnDTO(f"out{i}", "acc", d, 80000, Direction.OUT))
    return out


def _input(**kw) -> ForecastInput:
    base = dict(
        account_id="acc",
        as_of=date(2026, 2, 1),
        horizon_days=30,
        opening_balance_minor=500000,
        seed=42,
        txns=_week_of_txns(date(2026, 2, 1)),
        daily_balances=[],
        planned_events=[],
    )
    base.update(kw)
    return ForecastInput(**base)


def test_horizon_length_and_determinism() -> None:
    svc = BaselineForecastService()
    r1 = svc.run(_input())
    r2 = svc.run(_input())
    assert len(r1.points) == 30
    assert [p.balance_p50_minor for p in r1.points] == [p.balance_p50_minor for p in r2.points]
    # Без оценки неопределённости квантили совпадают, вероятность не задана.
    assert r1.points[0].balance_p10_minor == r1.points[0].balance_p50_minor
    assert r1.points[0].probability_negative is None
    assert r1.risk.available is False


def test_planned_event_moves_balance() -> None:
    svc = BaselineForecastService()
    due = date(2026, 2, 10)
    event = PlannedEventDTO(
        id="ev1",
        direction=Direction.OUT,
        amount_minor=1_000_000,
        remaining_amount_minor=1_000_000,
        due_date=due,
        status="planned",
        kind="invoice",
        source="manual",
        available_at=date(2026, 2, 1),
    )
    without = svc.run(_input())
    with_event = svc.run(_input(planned_events=[event]))
    idx = (due - date(2026, 2, 1)).days - 1
    # В день счёта отток больше ровно на сумму события.
    assert with_event.points[idx].outflow_minor - without.points[idx].outflow_minor == 1_000_000


def test_paid_event_not_counted() -> None:
    svc = BaselineForecastService()
    paid = PlannedEventDTO(
        id="ev2",
        direction=Direction.OUT,
        amount_minor=1_000_000,
        remaining_amount_minor=0,
        due_date=date(2026, 2, 10),
        status="paid",
        kind="invoice",
        source="manual",
        available_at=date(2026, 2, 1),
    )
    assert [p.outflow_minor for p in svc.run(_input(planned_events=[paid])).points] == [
        p.outflow_minor for p in svc.run(_input()).points
    ]
