"""Исследовательский движок: причинность, денежные тождества и fallback."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, PlannedEventDTO, ScenarioChange, TxnDTO
from app.modules.forecasting.v2.engine import METHODS, ExperimentalForecastService
from app.modules.forecasting.v2.quality import ForecastInputError


def history(days=84, *, zero=False, rising=False):
    as_of, balance = date(2026, 8, 31), 10_000
    txns, balances = [], []
    for index in range(days):
        day = as_of - timedelta(days=days - index - 1)
        incoming = 0 if zero else 100 + index * (10 if rising else 1)
        outgoing = 0 if zero else 80 + (index % 5) * 10
        txns.extend(
            [
                TxnDTO(f"in{index}", "a", day, incoming, Direction.IN),
                TxnDTO(f"out{index}", "a", day, outgoing, Direction.OUT),
            ]
        )
        balance += incoming - outgoing
        balances.append(DailyBalanceDTO("a", day, balance))
    return ForecastInput("a", as_of, 30, balance, 42, txns, balances, [])


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("horizon", [1, 7, 30, 90, 180])
def test_deterministic_all_horizons_components_and_probability_union(method, horizon):
    data = replace(history(), horizon_days=horizon)
    original = deepcopy(data)
    service = ExperimentalForecastService(method, paths=20)
    result = service.run(data)
    assert service.run(data) == result
    assert data == original
    assert len(result.points) == horizon
    assert result.risk.probability_any_negative >= max(p.probability_negative for p in result.points)
    for index, (point, component) in enumerate(zip(result.points, result.details["daily_components"], strict=True)):
        assert point.point_date == data.as_of + timedelta(days=index + 1)
        assert point.inflow_minor == component["irregular_in_minor"] + component["known_in_minor"]
        assert point.outflow_minor == component["irregular_out_minor"] + component["known_out_minor"]
        assert point.balance_p10_minor <= point.balance_p50_minor <= point.balance_p90_minor
        assert 0 <= point.probability_negative <= 1


def test_horizon_prefix_and_scenario_share_random_paths():
    service = ExperimentalForecastService("ewm", paths=40)
    data = history()
    short, long = service.run(replace(data, horizon_days=7)), service.run(data)
    assert short.points == long.points[:7]
    extra = service.run(
        replace(
            data, scenario=[ScenarioChange("add_expense", amount_minor=100, on_date=data.as_of + timedelta(days=2))]
        )
    )
    assert extra.points[0] == long.points[0]
    for original, changed in zip(long.points[1:], extra.points[1:], strict=True):
        assert changed.balance_p10_minor == original.balance_p10_minor - 100
        assert changed.balance_p50_minor == original.balance_p50_minor - 100
        assert changed.balance_p90_minor == original.balance_p90_minor - 100


def test_future_and_other_account_do_not_change_forecast():
    data = history()
    polluted = replace(
        data,
        txns=[
            *reversed(data.txns),
            TxnDTO("future", "a", data.as_of + timedelta(days=1), 999999, Direction.OUT),
            TxnDTO("foreign", "b", data.as_of, 999999, Direction.OUT),
        ],
        daily_balances=list(reversed(data.daily_balances)),
    )
    service = ExperimentalForecastService("trend", paths=20)
    assert service.run(data) == service.run(polluted)


@pytest.mark.parametrize("days", [0, 1, 7, 27])
def test_short_history_has_none_probability_and_plan_flows(days):
    data = history(days)
    event = PlannedEventDTO(
        "p", "out", 300, 100, data.as_of + timedelta(days=1), "partially_paid", "invoice", "manual", data.as_of
    )
    result = ExperimentalForecastService("mean", paths=20).run(replace(data, planned_events=[event]))
    assert not result.risk.available
    assert result.risk.probability_any_negative is None
    assert all(point.probability_negative is None for point in result.points)
    assert result.details["daily_components"][0]["known_out_minor"] == 100


def test_zero_history_has_zero_flow_without_fake_uncertainty():
    result = ExperimentalForecastService("winsor", paths=20).run(history(zero=True))
    assert all(point.inflow_minor == point.outflow_minor == 0 for point in result.points)
    assert all(point.balance_p10_minor == point.balance_p90_minor == 10000 for point in result.points)
    assert result.details["raw_probability_research_only"]


def test_ewm_recent_weights_trend_cap_and_winsor_preserve_facts():
    data = history(rising=True)
    original = deepcopy(data)
    mean = ExperimentalForecastService("mean", paths=20).run(data)
    ewm = ExperimentalForecastService("ewm", paths=20).run(data)
    trend = ExperimentalForecastService("trend", paths=20).run(data)
    winsor = ExperimentalForecastService("winsor", paths=20).run(data)
    assert ewm.points[0].inflow_minor > mean.points[0].inflow_minor
    assert 1 < trend.details["trend_factors"][0] <= 1.25
    assert winsor.details["clipped_model_days"] > 0
    assert winsor.points[0].inflow_minor <= mean.points[0].inflow_minor
    assert data == original


def test_stale_balance_disables_simulation_and_errors_are_explicit():
    data = history()
    stale = replace(data, as_of=data.as_of + timedelta(days=4))
    result = ExperimentalForecastService("mean", paths=20).run(stale)
    assert not result.risk.available and result.risk.probability_any_negative is None
    with pytest.raises(ForecastInputError, match="invalid_scenario"):
        ExperimentalForecastService("mean", paths=20).run(replace(data, scenario=[ScenarioChange("unknown")]))
    for method, paths in [("unknown", 20), ("mean", 0), ("mean", True)]:
        with pytest.raises(ValueError):
            ExperimentalForecastService(method, paths)


def test_large_split_recurrence_is_scheduled_once_and_closed_plan_suppresses_it():
    from app.modules.contracts import RecurrenceGroup, RecurrenceInterval
    from app.modules.forecasting.seasonal import _schedule

    data = history()
    members = [
        TxnDTO(str(index), "a", date(2026, 8, 31), 1, Direction.OUT, counterparty_name="Арендодатель")
        for index in range(3000)
    ]
    group = RecurrenceGroup(
        "g",
        Direction.OUT,
        RecurrenceInterval.MONTHLY,
        3000,
        None,
        None,
        0.9,
        [member.id for member in members],
        date(2026, 9, 30),
        "Дробление",
    )
    closed = PlannedEventDTO(
        "p",
        Direction.OUT,
        3000,
        0,
        date(2026, 9, 30),
        "paid",
        "invoice",
        "manual",
        data.as_of,
        counterparty_ref="арендодатель",
    )
    _, scheduled = _schedule(replace(data, txns=members), [group])
    assert scheduled == [(date(2026, 9, 30), Direction.OUT, 3000, "recurrence", "g")]
    _, scheduled = _schedule(replace(data, txns=members, planned_events=[closed]), [group])
    assert scheduled == []


def test_calendar_end_does_not_advance_past_date_max():
    from app.modules.contracts import RecurrenceGroup, RecurrenceInterval
    from app.modules.forecasting.seasonal import _schedule

    data = replace(history(), as_of=date.max - timedelta(days=180), horizon_days=180, txns=[])
    group = RecurrenceGroup(
        "g", Direction.OUT, RecurrenceInterval.MONTHLY, 1, None, None, 0.9, [], date.max, "Календарь"
    )
    assert _schedule(data, [group])[1] == [(date.max, Direction.OUT, 1, "recurrence", "g")]
