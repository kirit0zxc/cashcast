"""Пригодность данных, ошибки и пределы до дорогих вычислений."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, PlannedEventDTO, TxnDTO
from app.modules.forecasting.v2.quality import ForecastInputError, ResourceLimits, assess_quality, validate_input


def sample(days=84):
    as_of = date(2026, 8, 31)
    transactions, balances = [], []
    for index in range(days):
        day = as_of - timedelta(days=days - index - 1)
        transactions.append(TxnDTO(str(index), "acc", day, 100, Direction.IN))
        balances.append(DailyBalanceDTO("acc", day, 1000 + 100 * (index + 1)))
    return ForecastInput("acc", as_of, 30, 1000 + days * 100, 42, transactions, balances, [])


def test_quality_consistent_history_and_no_mutation():
    data = sample()
    original = deepcopy(data)
    quality = assess_quality(data)
    assert quality.mode == "empirical"
    assert quality.history_days == 84
    assert quality.eligible_for_probability
    assert quality.eligible_for_simulation
    assert not quality.reconciliation_breaks
    assert data == original
    assert quality.to_dict()["training_start"] == "2026-06-09"


def test_future_and_other_account_cannot_change_quality():
    data = sample()
    polluted = replace(
        data,
        txns=[
            *data.txns,
            TxnDTO("future", "acc", data.as_of + timedelta(days=1), 999999, Direction.OUT),
            TxnDTO("other", "other", data.as_of, 999999, Direction.OUT),
        ],
        daily_balances=[*data.daily_balances, DailyBalanceDTO("acc", data.as_of + timedelta(days=1), -999999)],
    )
    assert assess_quality(polluted) == assess_quality(data)
    assert validate_input(polluted) == validate_input(data)


def test_missing_data_not_fabricated_and_break_disables_probability():
    data = sample()
    corrupted = replace(
        data,
        daily_balances=[
            replace(balance, closing_balance_minor=-100) if index == 82 else balance
            for index, balance in enumerate(data.daily_balances)
        ],
    )
    original = deepcopy(corrupted)
    quality = assess_quality(corrupted)
    assert quality.reconciliation_breaks == 2
    assert not quality.eligible_for_probability
    assert quality.mode == "plan_only"
    assert corrupted == original


def test_short_stale_inconsistent_and_no_history_are_different():
    data = sample(40)
    assert assess_quality(data).eligible_for_simulation
    assert not assess_quality(data).eligible_for_probability
    assert not assess_quality(replace(data, opening_balance_minor=1)).eligible_for_simulation
    stale = replace(data, as_of=data.as_of + timedelta(days=4))
    assert assess_quality(stale).last_balance_age_days == 4
    assert not assess_quality(stale).eligible_for_probability
    assert assess_quality(replace(data, txns=[], daily_balances=[])).mode == "plan_only"


def test_unobserved_days_have_explicit_assumption():
    data = sample()
    selected = [txn for txn in data.txns if txn.booked_on.weekday() < 5]
    balance = 1000
    balances = []
    for txn in selected:
        balance += txn.amount_minor
        balances.append(DailyBalanceDTO("acc", txn.booked_on, balance))
    quality = assess_quality(replace(data, txns=selected, daily_balances=balances, opening_balance_minor=balance))
    assert quality.unobserved_calendar_days > 0
    assert any("условно нулевые" in warning for warning in quality.warnings)
    assert not quality.reconciliation_breaks


@pytest.mark.parametrize("horizon", [1, 7, 30, 90, 180])
def test_all_supported_horizons(horizon):
    assert validate_input(replace(sample(), horizon_days=horizon)).horizon_days == horizon


@pytest.mark.parametrize(
    "override",
    [
        dict(horizon_days=0),
        dict(horizon_days=181),
        dict(horizon_days=True),
        dict(seed=2**64),
        dict(seed=True),
        dict(opening_balance_minor=float("nan")),
        dict(txns=[None]),
    ],
)
def test_invalid_input_has_explicit_error(override):
    with pytest.raises(ForecastInputError) as error:
        validate_input(replace(sample(), **override))
    assert error.value.code in {"invalid_forecast_input", "forecast_resource_limit"}


def test_bad_currency_duplicates_dates_and_events_rejected():
    data = sample()
    event = PlannedEventDTO("ev", Direction.OUT, 100, 200, data.as_of, "planned", "invoice", "manual", data.as_of)
    invalid = [
        replace(data, txns=[replace(data.txns[0], currency="USD")]),
        replace(data, txns=[data.txns[0], data.txns[0]]),
        replace(data, daily_balances=[data.daily_balances[0], data.daily_balances[0]]),
        replace(data, planned_events=[event]),
    ]
    for value in invalid:
        with pytest.raises(ForecastInputError):
            validate_input(value)


def test_resource_limits_checked_before_computation():
    with pytest.raises(ForecastInputError, match="forecast_resource_limit"):
        validate_input(sample(), ResourceLimits(transactions=2))
    with pytest.raises(ForecastInputError, match="forecast_resource_limit"):
        data = sample()
        validate_input(replace(data, txns=[replace(data.txns[0], purpose="long")]), ResourceLimits(text_characters=1))


def test_identifier_is_validated_before_sorting_and_date_math_is_bounded():
    data = sample()
    with pytest.raises(ForecastInputError):
        validate_input(replace(data, txns=[data.txns[0], replace(data.txns[0], id=None)]))
    for as_of in (date.min, date.max):
        with pytest.raises(ForecastInputError):
            validate_input(replace(data, as_of=as_of))


def test_text_budget_includes_plans_scenarios_and_nested_fields():
    from app.modules.contracts import ScenarioChange

    data = replace(sample(), txns=[], daily_balances=[])
    event = PlannedEventDTO(
        "ev",
        Direction.OUT,
        100,
        100,
        data.as_of,
        "planned",
        "invoice",
        "manual",
        data.as_of,
        counterparty_ref="x" * 1000,
    )
    for polluted in (
        replace(data, planned_events=[event]),
        replace(data, scenario=[ScenarioChange("delay_event", target_id="x" * 1000)]),
    ):
        with pytest.raises(ForecastInputError, match="forecast_resource_limit"):
            validate_input(polluted, ResourceLimits(text_characters=500))


@pytest.mark.parametrize("invalid", [[], {}, 1, None])
def test_malformed_enum_types_raise_public_validation_error(invalid):
    data = sample()
    with pytest.raises(ForecastInputError):
        validate_input(replace(data, txns=[replace(data.txns[0], direction=invalid)]))
    event = PlannedEventDTO("ev", Direction.OUT, 100, 100, data.as_of, "planned", "invoice", "manual", data.as_of)
    with pytest.raises(ForecastInputError):
        validate_input(replace(data, planned_events=[replace(event, status=invalid)]))
