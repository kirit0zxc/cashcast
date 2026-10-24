"""Продуктовый fallback сохраняет точечный расчёт и не выдаёт слабый risk score за0."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, PlannedEventDTO, ScenarioChange, TxnDTO
from app.modules.forecasting.legacy_v1.seasonal import SeasonalForecastService
from app.modules.forecasting.service import get_forecast_service, get_supported_model_versions
from app.modules.forecasting.v2.legacy_limits import check_legacy_cost
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR, ForecastInputError
from app.modules.forecasting.v2.service import MODEL_VERSION, GuardedForecastService
from tests.analytics.test_engine_v2 import history


@pytest.mark.parametrize("horizon", [1, 7, 30, 90, 180])
def test_registered_guarded_deterministic_quality_and_none_risk_with_point_semantics(horizon):
    data = replace(history(), horizon_days=horizon)
    before = deepcopy(data)
    result = get_forecast_service(MODEL_VERSION).run(data)
    legacy = SeasonalForecastService().run(data)
    assert result.model_version == MODEL_VERSION
    assert get_forecast_service(MODEL_VERSION).run(data) == result
    assert data == before
    assert [replace(point, probability_negative=None) for point in legacy.points] == result.points
    assert not result.risk.available and result.risk.probability_any_negative is None
    assert result.details["risk_probability"]["status"] == "unavailable"
    assert "new_gap_quality_not_verified" in result.details["risk_probability"]["reasons"]
    for point, component in zip(result.points, result.details["daily_components"], strict=True):
        assert point.probability_negative is None
        assert point.inflow_minor == component["irregular_in_minor"] + component["known_in_minor"]
        assert point.outflow_minor == component["irregular_out_minor"] + component["known_out_minor"]


def test_minimum_sources_explanations_and_paired_scenario():
    data = history(zero=True)
    early = PlannedEventDTO(
        "early", "out", 11000, 11000, data.as_of + timedelta(days=1), "planned", "invoice", "manual", data.as_of
    )
    late = replace(
        early, id="late", due_date=data.as_of + timedelta(days=5), amount_minor=2000, remaining_amount_minor=2000
    )
    data = replace(data, planned_events=[early, late])
    service = GuardedForecastService()
    result = service.run(data)
    minimum = next(item for item in result.details["explanations"] if item["kind"] == "risk_minimum")
    assert minimum["detail"]["date"] == late.due_date.isoformat()
    assert {item["source_ref"] for item in minimum["detail"]["sources"]} == {"early", "late"}
    assert result.risk.related_event_ids == ["early", "late"]
    assert result.risk.first_negative_date == early.due_date
    assert result.risk.max_deficit_minor == 3000
    scenario = service.run(
        replace(data, scenario=[ScenarioChange("add_expense", amount_minor=100, on_date=early.due_date)])
    )
    assert scenario.points[0].balance_p50_minor == result.points[0].balance_p50_minor - 100
    assert scenario.risk.probability_any_negative is None


def test_reconciliation_break_excludes_earlier_statistical_and_recurrence_history():
    data = history()
    broken = replace(
        data,
        daily_balances=[
            *data.daily_balances[:-1],
            replace(data.daily_balances[-1], closing_balance_minor=data.opening_balance_minor + 1),
        ],
        opening_balance_minor=data.opening_balance_minor + 1,
    )
    result = GuardedForecastService().run(broken)
    assert result.details["quality"]["history_days"] == 0
    assert all(point.inflow_minor == point.outflow_minor == 0 for point in result.points)
    assert all(point.balance_p10_minor == point.balance_p90_minor for point in result.points)
    assert any("несверк" in warning for warning in result.data_warnings)


def test_legacy_resource_guard_counts_split_members_and_balance_scan_work():
    as_of = date(2026, 8, 31)
    txns = [
        TxnDTO(str(index), "a", day, 1, Direction.OUT, counterparty_ref="cp", category="rent")
        for index, day in enumerate([date(2026, 6, 30)] * 1000 + [date(2026, 7, 31)] * 1000 + [as_of] * 1000)
    ]
    data = ForecastInput("a", as_of, 30, 0, 42, txns, [], [])
    with pytest.raises(ForecastInputError, match="forecast_resource_limit"):
        check_legacy_cost(data)
    with pytest.raises(ForecastInputError, match="forecast_resource_limit"):
        get_forecast_service("seasonal-block-bootstrap-1.0-w84").run(data)
    txns = [
        replace(txn, booked_on=as_of - timedelta(days=index), counterparty_ref=None, category=None)
        for index, txn in enumerate(txns)
    ]
    balances = [DailyBalanceDTO("a", txn.booked_on, 0) for txn in txns]
    with pytest.raises(ForecastInputError, match="исторической сверки"):
        check_legacy_cost(replace(data, txns=txns, daily_balances=balances))


@pytest.mark.parametrize("version", get_supported_model_versions())
def test_output_money_budget_applies_to_all_registered_versions(version):
    data = history(zero=True)
    event = PlannedEventDTO(
        "overflow", Direction.IN, 1, 1, data.as_of + timedelta(days=1), "planned", "invoice", "manual", data.as_of
    )
    data = replace(
        data,
        opening_balance_minor=MAX_MONEY_MINOR,
        daily_balances=[replace(balance, closing_balance_minor=MAX_MONEY_MINOR) for balance in data.daily_balances],
        planned_events=[event],
    )
    with pytest.raises(ForecastInputError, match="forecast_resource_limit"):
        get_forecast_service(version).run(data)
