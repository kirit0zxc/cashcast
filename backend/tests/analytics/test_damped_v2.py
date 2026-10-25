"""Версия2.2: затухание к остатку на as_of сохраняет разброс и не трогает известные платежи."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, PlannedEventDTO, ScenarioChange, TxnDTO
from app.modules.forecasting.service import DEFAULT_MODEL_VERSION, get_forecast_service
from app.modules.forecasting.v2 import damped
from app.modules.forecasting.v2.damped import (
    FLOWS_ASSUMPTION,
    HORIZON_WARNING,
    MODEL_VERSION,
    SCENARIO_REASON,
    DampedForecastService,
)
from app.modules.forecasting.v2.estimated import MODEL_VERSION as ESTIMATED_VERSION
from app.modules.forecasting.v2.estimated import EstimatedForecastService
from app.modules.forecasting.v2.incremental_state import STATE_KEY

IDENTITY = {bucket: (1.0, 1.0) for bucket in damped.DAMPING}
ZERO = {bucket: (0.0, 0.0) for bucket in damped.DAMPING}
RENT = 40000


def history(days=120):
    as_of, balance = date(2026, 8, 31), 500_000
    txns, balances = [], []
    for offset in range(days):
        day = as_of - timedelta(days=days - offset - 1)
        today = [
            TxnDTO(f"i{offset}", "acc", day, 6000 if offset % 7 < 5 else 0, Direction.IN),
            TxnDTO(f"o{offset}", "acc", day, 3000 if offset % 9 < 5 else 8000, Direction.OUT),
        ]
        if day.day == 10:
            # Аренда одному контрагенту одной суммой — регулярность, к которой применяется β.
            today.append(TxnDTO(f"rent{offset}", "acc", day, RENT, Direction.OUT, counterparty_ref="7700000001"))
        txns.extend(today)
        balance += sum(t.amount_minor if t.direction == Direction.IN else -t.amount_minor for t in today)
        balances.append(DailyBalanceDTO("acc", day, balance))
    return ForecastInput("acc", as_of, 30, balance, 42, txns, balances, [])


def coefficients(monkeypatch, table, unreliable):
    monkeypatch.setattr(damped, "DAMPING", table)
    monkeypatch.setattr(damped, "UNRELIABLE_DRIFT", unreliable)


def test_registry_keeps_2_1_default_and_shipped_coefficients_are_shrinkage():
    assert DEFAULT_MODEL_VERSION == ESTIMATED_VERSION
    assert isinstance(get_forecast_service(MODEL_VERSION), DampedForecastService)
    assert list(damped.DAMPING) == [(1, 7), (8, 14), (15, 21), (22, 30)]
    assert all(0 <= value <= 1 for pair in damped.DAMPING.values() for value in pair)
    assert 0 <= damped.UNRELIABLE_DRIFT <= 1


def test_identity_coefficients_reproduce_2_1(monkeypatch):
    coefficients(monkeypatch, IDENTITY, 1.0)
    data = history()
    base, result = EstimatedForecastService().run(data), DampedForecastService().run(data)
    assert result.model_version == MODEL_VERSION
    assert result.points == base.points
    assert result.risk == base.risk
    assert result.details["point_method_version"] == damped.POINT_METHOD


def test_full_damping_centres_on_opening_and_keeps_spread(monkeypatch):
    coefficients(monkeypatch, ZERO, 0.0)
    data = history()
    base, result = EstimatedForecastService().run(data), DampedForecastService().run(data)
    assert result.risk.available and base.risk.available
    for old, new in zip(base.points, result.points, strict=True):
        # Банковское округление медианы чётного числа путей даёт расхождение не больше копейки.
        assert abs(new.balance_p50_minor - data.opening_balance_minor) <= 1
        width_old = old.balance_p90_minor - old.balance_p10_minor
        assert abs(new.balance_p90_minor - new.balance_p10_minor - width_old) <= 2
        assert (new.inflow_minor, new.outflow_minor) == (old.inflow_minor, old.outflow_minor)
    assert result.risk.probability_any_negative >= max(point.probability_negative for point in result.points)


def test_recurrence_is_damped_but_planned_event_is_kept(monkeypatch):
    data = history()
    planned = PlannedEventDTO("invoice", Direction.OUT, 70000, 70000, data.as_of + timedelta(days=3),
                              "planned", "invoice", "manual", data.as_of)
    data = replace(data, planned_events=[planned])
    coefficients(monkeypatch, {bucket: (1.0, 0.0) for bucket in damped.DAMPING}, 1.0)
    base, result = EstimatedForecastService().run(data), DampedForecastService().run(data)
    rent = [item for item in base.details["explanations"] if item["kind"] == "recurrence"]
    assert rent and all(item["amount_minor"] == RENT for item in rent)
    for old, new in zip(base.points, result.points, strict=True):
        removed = sum(item["amount_minor"] for item in rent if item["detail"]["date"] <= old.point_date.isoformat())
        # Без регулярности остаток выше ровно на аренду; плановое списание остаётся в обоих прогнозах.
        assert abs(new.balance_p50_minor - old.balance_p50_minor - removed) <= 1
    assert result.points[2].balance_p50_minor - result.points[1].balance_p50_minor < -60000


def planned(data, amount, day, event_id="invoice"):
    return PlannedEventDTO(event_id, Direction.OUT, amount, amount, data.as_of + timedelta(days=day),
                           "planned", "invoice", "manual", data.as_of)


def test_short_history_is_deterministic_damped_and_keeps_planned_event(monkeypatch):
    coefficients(monkeypatch, ZERO, 0.0)
    data = history(days=20)
    data = replace(data, planned_events=[planned(data, 70000, 3)])
    result = DampedForecastService().run(data)
    assert not result.risk.available and result.risk.probability_any_negative is None
    for day, point in enumerate(result.points, 1):
        assert point.balance_p10_minor == point.balance_p50_minor == point.balance_p90_minor
        assert point.balance_p50_minor == data.opening_balance_minor - (70000 if day >= 3 else 0)


def test_negative_date_and_deficit_follow_damped_median(monkeypatch):
    coefficients(monkeypatch, ZERO, 0.0)
    data = history()
    amount = data.opening_balance_minor + 100000
    data = replace(data, planned_events=[planned(data, amount, 4, "big")])
    result = DampedForecastService().run(data)
    assert result.risk.first_negative_date == data.as_of + timedelta(days=4)
    assert abs(result.risk.max_deficit_minor - 100000) <= 1
    assert result.risk.related_event_ids == ["big"]


@pytest.mark.parametrize("change", [
    ScenarioChange("add_expense", amount_minor=100, on_date=date(2026, 9, 5)),
    ScenarioChange("reduce_irregular_inflow", factor=0.5),
    ScenarioChange("increase_recurring", factor=2.0),
])
def test_scenario_keeps_full_effect_and_withholds_probability(monkeypatch, change):
    coefficients(monkeypatch, {bucket: (0.0, 0.0) for bucket in damped.DAMPING}, 0.0)
    data = history()
    with_change = replace(data, scenario=[change])
    base, scenario = DampedForecastService().run(data), DampedForecastService().run(with_change)
    old_base, old_scenario = EstimatedForecastService().run(data), EstimatedForecastService().run(with_change)
    # Сценарий = затухшая база + полный эффект: при α = β = 0 снижение выручки и рост регулярностей не исчезают.
    for new_b, new_s, old_b, old_s in zip(base.points, scenario.points, old_base.points, old_scenario.points,
                                          strict=True):
        assert abs((new_s.balance_p50_minor - new_b.balance_p50_minor)
                   - (old_s.balance_p50_minor - old_b.balance_p50_minor)) <= 2
    assert scenario.points[-1].balance_p50_minor < base.points[-1].balance_p50_minor
    assert scenario.risk.probability_any_negative is None
    assert all(point.probability_negative is None for point in scenario.points)
    assert scenario.details["risk_probability"]["reason"] == SCENARIO_REASON


def test_incremental_checkpoint_matches_full_and_keeps_2_1_paths():
    service = DampedForecastService()
    data = history()
    first = service.run(data)
    # В checkpoint остаются исходные траектории bootstrap — те же, что у2.1.
    assert (first.details[STATE_KEY]["prepared"]["residual_paths"]
            == EstimatedForecastService().run(data).details[STATE_KEY]["prepared"]["residual_paths"])
    changed = replace(data, planned_events=[planned(data, 20000, 2)])
    incremental = service.run(changed, state=first.details[STATE_KEY])
    full = service.run(changed)
    assert incremental.details["calculation"]["mode"] == "incremental"
    assert incremental.points == full.points
    assert incremental.risk == full.risk


@pytest.mark.parametrize("horizon", [1, 45, 90])
def test_shipped_coefficients_beyond_30_days_hold_opening_and_warn(horizon):
    data = replace(history(), horizon_days=horizon)
    result = DampedForecastService().run(data)
    assert len(result.points) == horizon
    # Аренда приходится на 10-й день, после недели β = 0: без плановых событий медиана — текущий остаток.
    assert all(abs(point.balance_p50_minor - data.opening_balance_minor) <= 1 for point in result.points)
    assert (HORIZON_WARNING in result.data_warnings) == (horizon > 30)
    assert FLOWS_ASSUMPTION in result.assumptions
