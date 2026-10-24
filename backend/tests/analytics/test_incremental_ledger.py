"""Дельты фактов против независимой frozen-математики, включая сдвиг календарного окна."""

import json
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, TxnDTO
from app.modules.forecasting.legacy_v1.seasonal import SeasonalForecastService
from app.modules.forecasting.v2.incremental_state import STATE_KEY
from app.modules.forecasting.v2.service import GuardedForecastService
from tests.analytics.test_incremental_forecast import comparable
from tests.analytics.test_seasonal import history


class FrozenReference:
    def run(self, data, prepared=None):
        result = SeasonalForecastService().run(data)
        self.prepared = {}
        self.metrics = {"bootstrap_paths_generated": result.details["paths"]}
        return result


def reference(data):
    # В независимом oracle исходные _history/detector/bootstrap, а не новый full-path.
    with patch("app.modules.forecasting.v2.service.IncrementalSeasonalService", FrozenReference):
        return GuardedForecastService().run(data)


def consistent(data, txns, as_of=None):
    # Применяем изменения фактов и подтверждённых EOD, не создавая искусственную несверку.
    as_of = as_of or data.as_of
    old_net = sum(t.amount_minor * (1 if t.direction == Direction.IN else -1) for t in data.txns)
    opening_before_history = data.opening_balance_minor - old_net
    start = min(t.booked_on for t in txns)
    balances, running = [], opening_before_history
    for offset in range((as_of - start).days + 1):
        day = start + timedelta(days=offset)
        running += sum(t.amount_minor * (1 if t.direction == Direction.IN else -1) for t in txns if t.booked_on == day)
        balances.append(DailyBalanceDTO(data.account_id, day, running))
    return replace(data, as_of=as_of, txns=txns, daily_balances=balances, opening_balance_minor=running)


@pytest.mark.parametrize("length", [7, 27, 55, 84])
@pytest.mark.parametrize("horizon", [1, 7, 30, 180])
def test_appended_days_slide_window_and_cross_simulation_threshold(length, horizon):
    data = replace(history(length), horizon_days=horizon)
    service = GuardedForecastService()
    base = service.run(data)
    assert comparable(base) == comparable(reference(data))
    for shift in [1, 2, 7]:
        day = data.as_of + timedelta(days=shift)
        txn = TxnDTO(f"added-{shift}", data.account_id, day, 1793 + shift, Direction.IN)
        updated = consistent(data, [*data.txns, txn], day)
        state = json.loads(json.dumps(base.details[STATE_KEY]))
        result = service.run(updated, state=state)
        assert comparable(result) == comparable(reference(updated))
        meta = result.details["calculation"]
        assert meta["mode"] == "incremental" and meta["reason"] == "observed_data_changed"
        assert meta["categorized_transactions"] == 1
        assert meta["reused_transactions"] == len(data.txns)
        data, base = updated, result


@pytest.mark.parametrize("change", ["append", "late", "amount", "date", "category", "remove", "direction"])
def test_same_cutoff_changes_old_history_without_resampling(change):
    data = history()
    txns = list(data.txns)
    if change in {"append", "late"}:
        day = data.as_of if change == "append" else data.as_of - timedelta(days=25)
        txns.append(TxnDTO("new", data.account_id, day, 777, Direction.IN, purpose="Оплата услуг"))
    elif change == "remove":
        txns.pop(51)
    else:
        field, value = {"amount": ("amount_minor", 4321), "date": ("booked_on", data.as_of - timedelta(days=11)),
                        "category": ("category", "rent"), "direction": ("direction", Direction.OUT)}[change]
        txns[50] = replace(txns[50], **{field: value})
    updated = consistent(data, txns)
    service = GuardedForecastService()
    state = json.loads(json.dumps(service.run(data).details[STATE_KEY]))
    with patch("app.modules.forecasting.v2.incremental_paths.random.Random", side_effect=AssertionError("RNG")):
        actual = service.run(updated, state=state)
    assert comparable(actual) == comparable(reference(updated))
    assert actual.details["calculation"]["categorized_transactions"] == (0 if change == "remove" else 1)


def test_recurrence_appears_splits_changes_bucket_and_expires():
    txns = [TxnDTO(str(m), "a", date(2026, m, 28), 10000, Direction.OUT,
                   counterparty_ref="rent", category="rent") for m in [1, 2]]
    data = ForecastInput("a", date(2026, 2, 28), 30, 100000, 42, txns, [], [])
    data = consistent(data, txns)
    engine = GuardedForecastService()
    base = engine.run(data)
    third = TxnDTO("3", "a", date(2026, 3, 28), 10000, Direction.OUT, counterparty_ref="rent", category="rent")
    stages = [
        ([*txns, third], date(2026, 3, 28)),
        ([*txns, replace(third, amount_minor=6000), replace(third, id="split", amount_minor=4000)], date(2026, 3, 28)),
        ([*txns, replace(third, counterparty_ref="other", category="fees")], date(2026, 3, 28)),
        ([*txns, third], date(2026, 3, 28)),
        ([*txns, third], date(2026, 5, 10)),
    ]
    for transactions, day in stages:
        updated = consistent(data, transactions, day)
        result = engine.run(updated, state=json.loads(json.dumps(base.details[STATE_KEY])))
        assert comparable(result) == comparable(reference(updated))
        assert result.details["calculation"]["mode"] == "incremental"
        data, base = updated, result


def test_reconciliation_break_and_repair_do_not_keep_obsolete_contributions():
    data = history()
    engine = GuardedForecastService()
    initial = engine.run(data)
    broken = replace(data, daily_balances=[*data.daily_balances[:-1],
                     replace(data.daily_balances[-1], closing_balance_minor=data.opening_balance_minor + 1)],
                     opening_balance_minor=data.opening_balance_minor + 1)
    result = engine.run(broken, state=initial.details[STATE_KEY])
    assert comparable(result) == comparable(reference(broken))
    repaired = engine.run(data, state=json.loads(json.dumps(result.details[STATE_KEY])))
    assert comparable(repaired) == comparable(reference(data))
