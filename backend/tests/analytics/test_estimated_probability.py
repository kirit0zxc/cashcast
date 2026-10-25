"""Вероятность — частота траекторий, с сохранением качества данных и старой версии."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.modules.contracts import PlannedEventDTO, ScenarioChange
from app.modules.forecasting.service import get_forecast_service
from app.modules.forecasting.v2.estimated import MODEL_VERSION, EstimatedForecastService
from app.modules.forecasting.v2.incremental_state import STATE_KEY
from app.modules.forecasting.v2.service import GuardedForecastService
from tests.analytics.test_engine_v2 import history


@pytest.mark.parametrize("horizon", [1, 7, 30, 90, 180])
def test_daily_and_any_probability_equal_saved_trajectory_counts(horizon):
    data = replace(history(), horizon_days=horizon)
    result = get_forecast_service(MODEL_VERSION).run(data)
    assert result.model_version == MODEL_VERSION
    assert result.risk.available
    paths = result.details[STATE_KEY]["prepared"]["residual_paths"]
    count = result.details["risk_probability"]["paths"]
    cumulative = 0
    negative_any = [False] * count
    for point, values, component in zip(result.points, paths, result.details["daily_components"], strict=True):
        cumulative += component["known_in_minor"] - component["known_out_minor"]
        negatives = [value + cumulative < 0 for value in values]
        assert point.probability_negative == sum(negatives) / count
        negative_any = [a or b for a, b in zip(negative_any, negatives, strict=True)]
    assert result.risk.probability_any_negative == sum(negative_any) / count
    assert result.risk.probability_any_negative >= max(p.probability_negative for p in result.points)
    assert result.details["risk_probability"]["calibrated"] is False
    legacy = GuardedForecastService().run(data)
    assert all(p.probability_negative is None for p in legacy.points)
    assert [replace(p, probability_negative=None) for p in result.points] == legacy.points


@pytest.mark.parametrize("case", ["short", "stale", "mismatch"])
def test_quality_guards_still_return_null(case):
    data = history(days=20) if case == "short" else history()
    if case == "stale":
        data = replace(data, as_of=data.as_of + timedelta(days=7))
    if case == "mismatch":
        data = replace(data, opening_balance_minor=data.opening_balance_minor + 1)
    result = EstimatedForecastService().run(data)
    assert not result.risk.available
    assert result.risk.probability_any_negative is None
    assert all(p.probability_negative is None for p in result.points)
    assert result.details["risk_probability"]["status"] == "unavailable"


def test_scenario_changes_probability_without_rewriting_base():
    data = history(zero=True)
    service = EstimatedForecastService()
    base = service.run(data)
    assert base.risk.probability_any_negative == 0
    scenario = service.run(replace(data, scenario=[ScenarioChange(
        kind="add_expense", on_date=data.as_of + timedelta(days=2), amount_minor=20000,
    )]))
    assert scenario.risk.probability_any_negative == 1
    assert scenario.points[0].probability_negative == 0
    assert scenario.points[1].probability_negative == 1
    assert service.run(data) == base


def test_incremental_plan_update_matches_full_probability():
    service = EstimatedForecastService()
    data = history(zero=True)
    first = service.run(data)
    event = PlannedEventDTO("expense", "out", 20000, 20000, data.as_of + timedelta(days=2),
                            "planned", "invoice", "manual", data.as_of)
    changed = replace(data, planned_events=[event])
    incremental = service.run(changed, state=first.details[STATE_KEY])
    full = service.run(changed)
    assert incremental.points == full.points
    assert incremental.risk == full.risk
    assert full.risk.probability_any_negative == 1
    assert incremental.details["calculation"]["mode"] == "incremental"
    assert incremental.details["calculation"]["bootstrap_paths_generated"] == 0


def test_existing_negative_balance_is_not_called_new_gap_probability():
    data = history(zero=True)
    data = replace(data, opening_balance_minor=-100,
                   daily_balances=[replace(day, closing_balance_minor=-100) for day in data.daily_balances])
    result = EstimatedForecastService().run(data)
    assert result.risk.probability_any_negative == 1
    assert result.details["risk_probability"]["scope"] == "any_negative_future_balance"
    assert result.details["risk_probability"]["opening_already_negative"] is True


def test_irregular_cashflow_produces_fractional_probability():
    data = history()
    txns, balances, balance = [], [], 10000
    for index, day in enumerate(data.daily_balances):
        incoming = 1000 if index % 13 == 0 else 0
        outgoing = 300 if index % 3 == 0 else 100
        txns.extend([replace(data.txns[index * 2], amount_minor=incoming),
                     replace(data.txns[index * 2 + 1], amount_minor=outgoing)])
        balance += incoming - outgoing
        balances.append(replace(day, closing_balance_minor=balance))
    offset = 200 - balance
    data = replace(data, opening_balance_minor=200, txns=txns,
                   daily_balances=[replace(day, closing_balance_minor=day.closing_balance_minor + offset)
                                   for day in balances])
    result = EstimatedForecastService().run(data)
    assert any(0 < point.probability_negative < 1 for point in result.points)
