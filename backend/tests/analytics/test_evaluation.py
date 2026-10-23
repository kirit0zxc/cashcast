"""Проверяем формулы метрик и границы факта независимо от модели."""

import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evaluation.backtest import Metrics, fold

from app.modules.contracts import Direction, ForecastPointDTO, ForecastResult, RiskSummary, TxnDTO


def test_metrics_against_hand_calculation():
    metric = Metrics()
    result = ForecastResult(
        "test",
        [
            ForecastPointDTO(date(2026, 1, 1), 12, 4, -10, 5, 10, 0.25),
            ForecastPointDTO(date(2026, 1, 2), 8, 6, -20, -5, 5, 0.75),
        ],
        RiskSummary(True, probability_any_negative=0.8),
    )
    metric.add(result, [(10, 5, 0), (10, 5, -10)], "short")
    report = metric.report()
    assert report["balance_mae_minor"] == 5
    assert report["balance_rmse_minor"] == 5
    assert report["inflow_wape"] == 0.2
    assert report["outflow_wape"] == 0.2
    assert report["interval_p10_p90_coverage"] == 1
    assert report["daily_negative_brier"] == 0.0625
    assert report["any_negative_brier"] == pytest.approx(0.04)
    assert report["risk_folds"] == 1


def test_unavailable_probability_is_not_scored_as_zero():
    metric = Metrics()
    result = ForecastResult("test", [ForecastPointDTO(date(2026, 1, 1), 0, 0, 0, 0, 0, None)], RiskSummary(False))
    metric.add(result, [(0, 0, -1)], "short")
    report = metric.report()
    assert report["risk_folds"] == report["risk_days"] == 0
    assert report["daily_negative_brier"] is None
    assert report["inflow_wape"] is None


def dataset():
    start = date(2026, 1, 1)
    txns = [TxnDTO(str(index), "company", start + timedelta(days=index), 100, Direction.IN) for index in range(65)]
    balances = {txn.booked_on: (index + 1) * 100 for index, txn in enumerate(txns)}
    return txns, balances


def test_fold_only_passes_past_and_verifies_targets():
    txns, balances = dataset()
    as_of = date(2026, 1, 30)
    (data, truth, cohort), reason = fold("company", txns, balances, as_of)
    assert reason is None and cohort == "short"
    assert all(txn.booked_on <= as_of for txn in data.txns)
    assert all(balance.balance_date <= as_of for balance in data.daily_balances)
    assert len(truth) == 30
    assert truth[-1][2] == 6000
    broken = dict(balances)
    broken[date(2026, 2, 1)] += 1
    assert fold("company", txns, broken, as_of)[1] == "unreconciled_future_target"
    trimmed = {day: value for day, value in balances.items() if day < as_of + timedelta(days=30)}
    assert fold("company", txns, trimmed, as_of)[1] == "unverified_end_coverage"
    altered = [replace(txn, amount_minor=999999) if txn.booked_on > as_of else txn for txn in txns]
    assert [txn for txn in altered if txn.booked_on <= as_of] == data.txns


def test_validation_view_cannot_use_september_for_target_quality_gate():
    from evaluation.backtest import HOLDOUT, temporal_view

    company = "c"
    txns = [
        TxnDTO("past", company, date(2026, 7, 31), 100, Direction.IN),
        TxnDTO("sep", company, date(2026, 9, 1), 999999, Direction.IN),
    ]
    balances = {date(2026, 7, 31): 100, date(2026, 9, 1): 1000099}
    view_txns, view_balances = temporal_view({company: txns}, {company: balances}, HOLDOUT)
    assert len(view_txns[company]) == 1
    assert max(view_balances[company]) <= HOLDOUT
    assert fold(company, view_txns[company], view_balances[company], date(2026, 7, 31))[1] == "unverified_end_coverage"
