"""Сверка банковских цепочек, отсутствие утечек и метрики редкого нового минуса."""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evaluation.real_data.berka import BerkaDaily
from evaluation.real_data.datasets import Day, MoneyVis, minor
from evaluation.real_data.models import FlowCandidate, FlowFeatures
from evaluation.real_data.risk import build_folds, metrics


def statement(path, rows):
    fields = ["Transaction Number", "Transaction Date", "Credit Amount", "Debit Amount", "Balance"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(dict(zip(fields, row, strict=True)) for row in rows)


def test_moneyvis_reversed_same_day_order_last_balance_and_missing_calendar(tmp_path):
    path = tmp_path / "sample.csv"
    statement(
        path,
        [("3", "03/01/2020", "", "2", "7"), ("2", "01/01/2020", "", "1", "9"), ("1", "01/01/2020", "10", "", "10")],
    )
    days, audit = MoneyVis.read(path)
    assert [(d.incoming, d.outgoing, d.balance) for d in days] == [(1000, 100, 900), (0, 0, 900), (0, 200, 700)]
    assert audit["verified_links"] == 2
    assert audit["currency"] == "unspecified_in_csv"


@pytest.mark.parametrize(
    "row",
    [
        ("1", "01/01/2020", "", "1", "9"),  # дубль ID
        ("2", "01/01/2020", "", "1", "8"),  # несверка
        ("2", "01/01/2020", "2", "1", "11"),  # оба направления
        ("2", "01/01/2020", "", "0.001", "9.999"),  # дробная копейка
    ],
)
def test_moneyvis_invalid_data_fails_closed(tmp_path, row):
    path = tmp_path / "bad.csv"
    statement(path, [row, ("1", "01/01/2020", "10", "", "10")])
    with pytest.raises(ValueError):
        MoneyVis.read(path)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1.001"])
def test_no_nonfinite_or_rounded_money(value):
    with pytest.raises(ValueError):
        minor(value)


def test_berka_reconstructs_out_of_order_and_rejects_disconnected_edges():
    assert BerkaDaily.endpoint([(100, 20), (0, 100), (20, -10)], 0) == -10
    assert BerkaDaily.endpoint([(0, 100), (100, 0), (0, 50)], 0) == 50
    assert BerkaDaily.endpoint([(0, 100), (200, 300)], 0) is None
    assert BerkaDaily.endpoint([(0, 100), (0, 50)], 0) is None


def test_berka_unknown_balance_propagates_until_verified_recovery(tmp_path):
    path = tmp_path / "berka.csv"
    path.write_text(
        "account_id;date;type;amount;balance\n"
        "1;930101;PRIJEM;10;10\n"
        "1;930102;PRIJEM;1;21\n"
        "1;930102;PRIJEM;1;31\n"
        "1;930105;PRIJEM;2;42\n"
        "1;930106;VYDAJ;3;39\n",
        encoding="utf-8",
    )
    _, days, invalid = next(BerkaDaily.read(path))
    assert {date(1993, 1, i) for i in (2, 3, 4, 5)} == invalid
    assert days[-1].balance == 3900


def test_risk_metrics_ties_single_class_and_false_alarms():
    perfect = metrics([0, 1], [0.2, 0.8], 0.5, 0.5)
    assert perfect["roc_auc"] == perfect["average_precision"] == 1
    assert perfect["brier"] == pytest.approx(0.04)
    ties = metrics([1, 0], [0.5, 0.5], 0.5, 0.5)
    assert ties["roc_auc"] == ties["average_precision"] == 0.5
    absent = metrics([0, 0], [0.1, 0.9], 0.5, 0.1)
    assert absent["roc_auc"] is absent["recall"] is None
    assert absent["fp"] == 1 and absent["fpr"] == 0.5


def test_berka_recovers_chain_with_return_to_start_then_excludes_recovery_day(tmp_path):
    path = tmp_path / "berka.csv"
    path.write_text(
        "account_id;date;type;amount;balance\n"
        "1;930101;PRIJEM;10;10\n"
        "1;930102;PRIJEM;5;25\n"
        "1;930102;VYDAJ;5;20\n"
        "1;930102;VYDAJ;2;18\n"
        "1;930103;PRIJEM;1;19\n",
        encoding="utf-8",
    )
    _, days, invalid = next(BerkaDaily.read(path))
    assert invalid == {date(1993, 1, 2)}
    assert days[-1].balance == 1900


def test_recursive_prediction_uses_predictions_not_future_truth():
    history = [Day(date(2020, 1, 1) + timedelta(days=i), 100, 50, 10000) for i in range(84)]
    inputs = []

    class PreviousIncoming:
        def predict(self, rows):
            inputs.append(rows[0])
            return [rows[0][3] + 1]

    model = FlowCandidate()
    model.models = [PreviousIncoming(), PreviousIncoming()]
    forecast = model.predict(history, 2)
    assert forecast[0].incoming == 200 and forecast[1].incoming == 300
    assert len(history) == 84 and history[-1].incoming == 100
    assert inputs[2][3] == 2
    with pytest.raises(ValueError):
        FlowFeatures.make(history, history[-1].date)


def test_late_account_not_claimed_to_be_seen_in_training(monkeypatch):
    history = [Day(date(1997, 1, 1) + timedelta(days=i), 0, 0, 100) for i in range(730)]
    monkeypatch.setattr(BerkaDaily, "read", lambda _: iter([("1", history, set())]))
    groups, _ = build_folds(Path("unused"))
    assert not groups["train"]
    assert groups["test_development_accounts"]
    assert not groups["test_unseen_accounts"]


def test_risk_folds_do_not_cross_year_boundary_or_invalid_days(monkeypatch):
    history = [Day(date(1996, 1, 1) + timedelta(days=i), 0, 0, 100) for i in range(1096)]
    monkeypatch.setattr(BerkaDaily, "read", lambda _: iter([("1", history, set())]))
    monkeypatch.setattr("evaluation.real_data.risk.features", lambda h: [h[0].date, h[-1].date])
    groups, _ = build_folds(Path("unused"))
    for phase, rows in groups.items():
        for (start, cutoff), _, _ in rows:
            assert (cutoff - start).days == 83
            target_start, target_end = cutoff + timedelta(days=1), cutoff + timedelta(days=30)
            if phase == "train":
                assert target_end <= date(1996, 12, 31)
            else:
                assert target_start.year == target_end.year == (1997 if phase == "validation" else 1998)
    monkeypatch.setattr(BerkaDaily, "read", lambda _: iter([("1", history, {d.date for d in history})]))
    groups, audit = build_folds(Path("unused"))
    assert not any(groups.values()) and audit["excluded_windows"] > 0
