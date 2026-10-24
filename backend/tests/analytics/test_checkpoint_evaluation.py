"""Метрики по ручным примерам, причинность и явная неизвестность факта."""

import json
from copy import deepcopy
from datetime import date, timedelta

import pytest

from app.modules.evaluation.export import EvaluationExport
from app.modules.evaluation.metrics import EvaluationMetrics as Metrics
from app.modules.evaluation.service import CheckpointEvaluation
from app.modules.forecasting.service import DEFAULT_MODEL_VERSION


def dataset():
    start = date(2025, 1, 1)
    transactions, balances = [], []
    balance = 100_000
    for index in range(110):
        day = str(start + timedelta(days=index))
        amount = 1000 + (index % 7) * 100
        balance -= amount
        transactions.append(
            {
                "id": str(index),
                "account_id": "account",
                "booked_on": day,
                "amount_minor": amount,
                "direction": "out",
                "currency": "RUB",
                "counterparty_ref": None,
                "purpose": "PRIVATE_MARKER",
                "category": None,
            }
        )
        balances.append({"date": day, "balance_minor": balance})
    raw = {"account_id": "account", "transactions": transactions, "balances": balances}
    return {
        **raw,
        "dataset_sha256": CheckpointEvaluation.fingerprint(raw),
        "model_version": DEFAULT_MODEL_VERSION,
        "config": {
            "as_of": str(start + timedelta(days=69)),
            "horizon_days": 10,
            "folds": 3,
            "threshold": 0.5,
            "seed": 42,
            "complete_statement": True,
            "source_sha256": None,
        },
    }


def test_metrics_manual_values_and_units():
    regression = Metrics.regression([(100, 200), (400, 200)])
    assert regression["mae"]["value"] == 1.5
    assert regression["mse"]["value"] == 2.5
    result = Metrics.classification([(1, 0.9), (0, 0.8), (1, 0.2), (0, 0.1)])
    assert result["confusion_matrix"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    for name in ("accuracy", "precision", "recall", "f1"):
        assert result["metrics"][name]["value"] == 0.5
    assert result["metrics"]["roc_auc"]["value"] == 0.75
    assert result["metrics"]["average_precision"]["value"] == pytest.approx(5 / 6)
    tied = Metrics.classification([(1, 0.5), (0, 0.5)])
    assert tied["metrics"]["roc_auc"]["value"] == 0.5
    assert tied["metrics"]["average_precision"]["value"] == 0.5


def test_undefined_metrics_are_not_fake_zero_or_nan():
    for pairs in ([], [(0, 0.1)], [(1, 0.9)]):
        result = Metrics.classification(pairs)
        assert result["metrics"]["roc_auc"]["value"] is None
        assert result["metrics"]["roc_auc"]["unavailable_reason"]
        json.dumps(result, allow_nan=False)
    assert Metrics.classification([(0, 0.1)])["metrics"]["recall"]["value"] is None
    assert Metrics.classification([(1, 0.1)])["metrics"]["f1"]["value"] == 0


def test_real_engine_reproducible_no_future_leak_or_private_logs():
    payload = dataset()
    first = CheckpointEvaluation.run(payload)
    assert first == CheckpointEvaluation.run(payload)
    assert first["regression"]["balance"]["n"] == 30
    assert first["daily_median_negative"]["n"] == 30
    assert "PRIVATE_MARKER" not in json.dumps(first)
    changed = deepcopy(payload)
    for txn in changed["transactions"]:
        if txn["booked_on"] > payload["config"]["as_of"]:
            txn["amount_minor"] *= 999
    for balance in changed["balances"]:
        if balance["date"] > payload["config"]["as_of"]:
            balance["balance_minor"] -= 1_000_000
    second = CheckpointEvaluation.run(changed)
    for a, b in zip(first["windows"][0]["points"], second["windows"][0]["points"], strict=True):
        for field in ("balance_p50_minor", "inflow_minor", "probability_negative"):
            assert a[field] == b[field]
    assert first["regression"] != second["regression"]


def test_missing_truth_requires_explicit_complete_and_reconciled_statement():
    payload = dataset()
    missing = str(date.fromisoformat(payload["config"]["as_of"]) + timedelta(days=1))
    payload["balances"] = [b for b in payload["balances"] if b["date"] != missing]
    payload["config"]["complete_statement"] = False
    report = CheckpointEvaluation.run(payload)
    assert report["regression"]["balance"]["n"] == 29
    assert report["regression"]["inflow"]["n"] == 0
    assert report["windows"][0]["actual_new_gap"] is None
    payload["config"]["complete_statement"] = True
    reconstructed = CheckpointEvaluation.run(payload)
    assert reconstructed["regression"]["balance"]["n"] == 30
    assert reconstructed["windows"][0]["points"][0]["balance_source"] == "reconstructed"
    payload["transactions"][71]["amount_minor"] += 100
    broken = CheckpointEvaluation.run(payload)
    assert broken["windows"][0]["points"][0]["actual_balance_minor"] is None
    assert broken["windows"][0]["reconciliation_breaks"] > 0


def test_existing_negative_is_not_new_gap_and_missing_cutoff_skipped():
    payload = dataset()
    for balance in payload["balances"]:
        balance["balance_minor"] -= 1_000_000
    report = CheckpointEvaluation.run(payload)
    assert report["horizon_new_gap"]["n"] == 0
    assert report["daily_median_negative"]["n"] == 30
    payload["balances"] = [b for b in payload["balances"] if b["date"] != payload["config"]["as_of"]]
    report = CheckpointEvaluation.run(payload)
    assert report["windows"][0]["status"] == "skipped"


def test_export_is_self_contained_and_escapes_untrusted_text():
    report = CheckpointEvaluation.run(dataset())
    report["limitations"].append('<script>alert("x")</script>')
    html = EvaluationExport.html(report)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<svg" in html and "ROC-AUC" not in html  # технические имена метрик сохранены
    assert "roc_auc" in html and "Пошаговый журнал" in html
    assert "PRIVATE_MARKER" not in html
