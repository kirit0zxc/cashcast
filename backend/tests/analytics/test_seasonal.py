"""Причинность, интервалы риска, компоненты и неизменяемые сценарии."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, PlannedEventDTO, ScenarioChange, TxnDTO
from app.modules.forecasting.seasonal import SeasonalForecastService


def history(days=84):
    as_of = date(2026, 8, 31)
    txns, balances = [], []
    balance = 100000
    for offset in range(days):
        day = as_of - timedelta(days=days - offset - 1)
        incoming = 5000 if offset % 7 < 5 else 0
        outgoing = 3000 if offset % 9 < 5 else 7000
        txns.extend(
            [
                TxnDTO(f"i{offset}", "acc", day, incoming, Direction.IN),
                TxnDTO(f"o{offset}", "acc", day, outgoing, Direction.OUT),
            ]
        )
        balance += incoming - outgoing
        balances.append(DailyBalanceDTO("acc", day, balance))
    return ForecastInput("acc", as_of, 30, balance, 42, txns, balances, [])


def event(data, **kwargs):
    return replace(
        PlannedEventDTO(
            "event",
            Direction.OUT,
            50000,
            50000,
            data.as_of + timedelta(days=5),
            "planned",
            "invoice",
            "manual",
            data.as_of,
        ),
        **kwargs,
    )


def test_determinism_causality_json_and_risk_union():
    import json

    data = history()
    service = SeasonalForecastService(paths=50)
    result = service.run(data)
    assert result == service.run(deepcopy(data))
    polluted = replace(
        data,
        txns=[
            *reversed(data.txns),
            TxnDTO("future", "acc", data.as_of + timedelta(days=1), 99999999, Direction.IN),
            TxnDTO("other", "other", data.as_of, 99999999, Direction.IN),
        ],
        daily_balances=[*data.daily_balances, DailyBalanceDTO("acc", data.as_of + timedelta(days=1), 9999999)],
        planned_events=[event(data, available_at=data.as_of + timedelta(days=1))],
    )
    assert service.run(polluted) == result
    assert result.risk.available
    assert len(result.points) == 30
    for point in result.points:
        assert point.balance_p10_minor <= point.balance_p50_minor <= point.balance_p90_minor
        assert 0 <= point.probability_negative <= result.risk.probability_any_negative <= 1
        assert isinstance(point.inflow_minor, int)
    json.dumps(result.details)


def test_short_empty_and_broken_history_no_fake_probability():
    service = SeasonalForecastService(paths=30)
    for data in [
        history(5),
        replace(history(), txns=[], daily_balances=[]),
        replace(
            history(),
            daily_balances=[
                replace(b, closing_balance_minor=b.closing_balance_minor + 1) if i == 80 else b
                for i, b in enumerate(history().daily_balances)
            ],
        ),
    ]:
        result = service.run(data)
        assert not result.risk.available
        assert result.risk.probability_any_negative is None
        assert all(point.probability_negative is None for point in result.points)
        assert result.data_warnings


def test_planned_event_and_scenario_do_not_mutate_base():
    data = history()
    data = replace(data, planned_events=[event(data)])
    original = deepcopy(data)
    service = SeasonalForecastService(paths=30)
    base = service.run(data)
    expense = replace(
        data, scenario=[ScenarioChange("add_expense", amount_minor=10000, on_date=data.as_of + timedelta(days=1))]
    )
    scenario = service.run(expense)
    assert data == original
    assert base == service.run(data)
    assert all(
        after.balance_p50_minor == before.balance_p50_minor - 10000
        for before, after in zip(base.points, scenario.points, strict=True)
    )
    delayed = service.run(replace(data, scenario=[ScenarioChange("delay_event", target_id="event", shift_days=5)]))
    assert delayed.points[4].outflow_minor == base.points[4].outflow_minor - 50000
    assert delayed.points[9].outflow_minor == base.points[9].outflow_minor + 50000
    reduced = service.run(replace(data, scenario=[ScenarioChange("reduce_irregular_inflow", factor=0.5)]))
    assert all(
        after.inflow_minor <= before.inflow_minor for before, after in zip(base.points, reduced.points, strict=True)
    )


def recurring_input():
    data = history()
    rents = [
        TxnDTO(
            f"rent{month}",
            "acc",
            date(2026, month, 28),
            10000,
            Direction.OUT,
            counterparty_ref="0012345678",
            purpose="Аренда",
            category="rent",
        )
        for month in (6, 7, 8)
    ]
    # Остатки не подменяем: тест компонентов не претендует на валидную статистику риска.
    return replace(data, txns=rents, daily_balances=[])


def test_recurring_replaced_by_explicit_partial_event_and_delay_not_double_counted():
    data = recurring_input()
    service = SeasonalForecastService(paths=30)
    base = service.run(data)
    assert base.details["recurrence_count"] == 1
    planned = event(
        data, due_date=date(2026, 9, 28), counterparty_ref="0012345678", amount_minor=10000, remaining_amount_minor=4000
    )
    with_plan = service.run(replace(data, planned_events=[planned]))
    assert sum(point.outflow_minor for point in with_plan.points) == 4000
    assert sum(point.outflow_minor for point in base.points) == 10000
    delayed = service.run(
        replace(data, planned_events=[planned], scenario=[ScenarioChange("delay_event", "event", shift_days=10)])
    )
    assert sum(point.outflow_minor for point in delayed.points) == 0
    group_id = base.details["recurrence_ids"][0]
    increased = service.run(replace(data, scenario=[ScenarioChange("increase_recurring", group_id, factor=1.5)]))
    assert sum(point.outflow_minor for point in increased.points) == 15000


@pytest.mark.parametrize(
    "change",
    [
        ScenarioChange("unknown"),
        ScenarioChange("delay_event", "missing", shift_days=1),
        ScenarioChange("reduce_irregular_inflow", factor=-1),
        ScenarioChange("reduce_irregular_inflow", factor=float("nan")),
        ScenarioChange("increase_recurring", "missing", factor=2),
        ScenarioChange("add_expense", amount_minor=-1, on_date=date(2026, 9, 1)),
    ],
)
def test_invalid_scenario_rejected(change):
    with pytest.raises(ValueError):
        SeasonalForecastService().run(replace(history(), scenario=[change]))


def test_currency_and_duplicates_rejected():
    data = history()
    with pytest.raises(ValueError):
        SeasonalForecastService().run(replace(data, txns=[replace(data.txns[0], currency="USD")]))
    with pytest.raises(ValueError):
        SeasonalForecastService().run(replace(data, txns=[data.txns[0], data.txns[0]]))


@pytest.mark.parametrize("status", ["paid", "cancelled"])
def test_closed_explicit_event_suppresses_recurrence(status):
    data = recurring_input()
    planned = event(
        data,
        due_date=date(2026, 9, 28),
        counterparty_ref="0012345678",
        amount_minor=10000,
        remaining_amount_minor=0,
        status=status,
    )
    result = SeasonalForecastService(paths=30).run(replace(data, planned_events=[planned]))
    assert sum(point.outflow_minor for point in result.points) == 0


def test_snapshot_name_identity_replaces_inn_recurrence():
    data = recurring_input()
    data = replace(data, txns=[replace(txn, counterparty_name="Арендодатель") for txn in data.txns])
    planned = event(
        data,
        due_date=date(2026, 9, 28),
        counterparty_ref="Арендодатель",
        amount_minor=10000,
        remaining_amount_minor=4000,
    )
    result = SeasonalForecastService(paths=30).run(replace(data, planned_events=[planned]))
    assert sum(point.outflow_minor for point in result.points) == 4000
