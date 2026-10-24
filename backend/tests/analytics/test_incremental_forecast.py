"""Частичный календарь равен полному расчёту и действительно не запускает bootstrap."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.modules.contracts import Direction, ScenarioChange
from app.modules.forecasting.v2.incremental_state import STATE_KEY, IncrementalState
from app.modules.forecasting.v2.service import GuardedForecastService
from tests.analytics.test_seasonal import event, history


def comparable(result):
    # Только служебные сведения об исполнении различаются; продуктовые поля совпадают.
    return replace(result, details={k: v for k, v in result.details.items()
                                    if k not in {STATE_KEY, "calculation"}})


@pytest.mark.parametrize("days", [7, 84])
@pytest.mark.parametrize("amount", [1, 2, 999999, 90000001])
def test_add_edit_cancel_and_json_restart_equal_full_without_history_or_random(days, amount):
    data = history(days)
    engine = GuardedForecastService()
    first = engine.run(data)
    original = deepcopy(first)
    plan = event(data, amount_minor=amount, remaining_amount_minor=amount)
    variants = [
        [plan],
        [replace(plan, due_date=plan.due_date + timedelta(days=2))],
        [replace(plan, direction=Direction.IN)],
        [replace(plan, status="partially_paid", remaining_amount_minor=amount // 2)],
        [replace(plan, status="cancelled")],
        [],
    ]
    for index, plans in enumerate(variants):
        changed = replace(data, planned_events=plans, data_version=str(index))
        expected = engine.run(changed)
        state = json.loads(json.dumps(first.details[STATE_KEY]))
        with (patch("app.modules.forecasting.v2.incremental_engine._history", side_effect=AssertionError("history")),
              patch("app.modules.forecasting.v2.incremental_engine.get_recurrence_detector",
                    side_effect=AssertionError("recurrence")),
              patch("app.modules.forecasting.v2.incremental_engine.random.Random", side_effect=AssertionError("RNG"))):
            updated = engine.run(changed, state=state)
        assert comparable(updated) == comparable(expected)
        assert updated.details["calculation"]["mode"] == "incremental"
        assert updated.details["calculation"]["bootstrap_paths_generated"] == 0
        first = updated
    assert original == engine.run(data)


@pytest.mark.parametrize("field", ["txns", "daily_balances", "as_of", "seed", "horizon_days",
                                  "opening_balance_minor", "scenario", "account_id"])
def test_non_calendar_change_invalidates_checkpoint(field):
    data = history()
    state = GuardedForecastService().run(data).details[STATE_KEY]
    values = {
        "txns": [replace(data.txns[0], amount_minor=999), *data.txns[1:]],
        "daily_balances": [], "as_of": data.as_of + timedelta(days=1), "seed": data.seed + 1,
        "horizon_days": 31, "opening_balance_minor": data.opening_balance_minor + 1,
        "scenario": [ScenarioChange("add_expense", amount_minor=1, on_date=data.as_of + timedelta(days=1))],
        "account_id": "other",
    }
    assert IncrementalState.unpack(replace(data, **{field: values[field]}), state) is None


def test_corrupted_and_old_state_falls_back_to_full():
    data = history()
    engine = GuardedForecastService()
    full = engine.run(data)
    broken = deepcopy(full.details[STATE_KEY])
    broken["prepared"]["residual_paths"][0][0] += 1
    for state in (None, {}, broken, {**full.details[STATE_KEY], "version": "old"}):
        assert engine.run(data, state=state) == full


def test_recurring_event_replacement_and_paid_event_keep_no_double_count():
    data = history()
    # Три месячных платежа задают регулярность, которую конкретный план замещает.
    from calendar import monthrange
    from datetime import date

    from app.modules.contracts import TxnDTO

    txns = [TxnDTO(str(m), data.account_id, date(2026, m, monthrange(2026, m)[1]),
                   10000, Direction.OUT, category="rent", counterparty_ref="landlord") for m in [6, 7, 8]]
    data = replace(data, txns=txns, daily_balances=[])
    engine = GuardedForecastService()
    first = engine.run(data)
    assert first.details["recurrence_count"] == 1
    plan = event(data, due_date=data.as_of + timedelta(days=30), amount_minor=10001,
                 remaining_amount_minor=10001, counterparty_ref="landlord")
    for status in ["planned", "paid", "cancelled"]:
        changed = replace(data, planned_events=[replace(plan, status=status,
                          remaining_amount_minor=0 if status == "paid" else plan.remaining_amount_minor)])
        assert comparable(engine.run(changed, state=first.details[STATE_KEY])) == comparable(engine.run(changed))
