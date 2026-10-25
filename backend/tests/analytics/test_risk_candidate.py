"""Границы обучения, выбор порога и независимость нового кандидата от будущего."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evaluation.real_data.datasets import Day
from evaluation.risk_candidate.data import CandidateDataset
from evaluation.risk_candidate.features import LiquidityFeatures
from evaluation.risk_candidate.run import CandidateComparison


@pytest.mark.parametrize(("start", "end", "heldout", "expected"), [
    (date(1996, 12, 2), date(1996, 12, 31), False, "train"),
    (date(1996, 12, 2), date(1996, 12, 31), True, None),
    (date(1996, 12, 3), date(1997, 1, 1), False, None),
    (date(1997, 1, 1), date(1997, 1, 30), False, "validation"),
    (date(1997, 1, 1), date(1997, 1, 30), True, None),
    (date(1998, 1, 1), date(1998, 1, 30), True, "test_unseen_accounts"),
    (date(1998, 1, 1), date(1998, 1, 30), False, "test_development_accounts"),
])
def test_target_boundaries_and_heldout_accounts(start, end, heldout, expected):
    assert CandidateDataset.phase(start, end, heldout) == expected


def test_weights_give_accounts_equal_total_influence():
    rows = [(None, 0, "a"), (None, 1, "a"), (None, 0, "b")]
    weights = CandidateDataset.weights(rows)
    assert sum(weights) == pytest.approx(3)
    assert weights[0] + weights[1] == weights[2]
    with pytest.raises(ValueError):
        CandidateDataset.weights([])


def test_features_history_length_and_known_deltas():
    history = [Day(date(1996, 1, 1) + timedelta(days=i), 100, 200, 10000 - i * 100) for i in range(84)]
    values = LiquidityFeatures.build(history)
    assert values[17:20] == [-3.5, -14, -41.5]
    assert values[-5:] == [0, 1, 1, 1, 1]
    assert len(values) == 29
    with pytest.raises(ValueError):
        LiquidityFeatures.build(history[:-1])


def test_dense_train_keeps_evaluation_windows_and_no_future_features(monkeypatch):
    # Первый обычный счёт без hash-heldout; все дни сверены.
    import hashlib

    from evaluation.real_data.berka import BerkaDaily
    account = next(str(i) for i in range(20) if hashlib.sha256(str(i).encode()).digest()[0] % 5 != 0)
    days = [Day(date(1996, 1, 1) + timedelta(days=i), 100, 100, 10000) for i in range(1000)]
    monkeypatch.setattr(BerkaDaily, "read", lambda _path: [(account, days, set())])
    groups, _ = CandidateDataset.build(None)
    assert len(groups["train"]) > 30
    expected = [i for i in range(83, len(days) - 30, 30)
                if days[i + 1].date.year == days[i + 30].date.year == 1997]
    assert len(groups["validation"]) == len(expected)
    before = groups["train"][0]
    # Изменяем только будущую цель самого первого окна: признак остаётся прежним.
    days[84] = Day(days[84].date, 0, 20000, -10000)
    changed, _ = CandidateDataset.build(None)
    assert before[0] == changed["train"][0][0]
    assert before[1] == 0 and changed["train"][0][1] == 1


def test_threshold_selection_and_explicit_no_allowed_point():
    selected, _ = CandidateComparison.select([1] * 10 + [0] * 990, [0.1] * 10 + [0.001] * 990, 0.01)
    assert selected["threshold"] == 0.1
    assert CandidateComparison.policy(selected)
    selected, _ = CandidateComparison.select([1, 0], [0.9, 0.9], 0.01)
    assert selected is None
    assert not CandidateComparison.policy(selected)


def test_improvement_requires_all_three_predeclared_metrics():
    baseline = {"average_precision": 0.2, "brier": 0.01, "f2": 0.3}
    better = {"average_precision": 0.3, "brier": 0.009, "f2": 0.4}
    assert CandidateComparison.improved(better, baseline)
    assert not CandidateComparison.improved({**better, "brier": 0.02}, baseline)
    assert not CandidateComparison.improved({**better, "f2": 0.2}, baseline)
    assert not CandidateComparison.improved({**better, "average_precision": 0.1}, baseline)


def test_paired_account_bootstrap_preserves_zero_difference():
    rows = [(None, 1, "a"), (None, 0, "a"), (None, 0, "b")]
    result = CandidateComparison.paired_brier(rows, [0.1, 0.2, 0.3], [0.1, 0.2, 0.3])
    assert result["estimate"] == 0
    assert result["ci95"] == [0, 0]
    assert result["replicates"] == 500


def test_published_result_matches_frozen_code_and_baseline():
    from evaluation.risk_candidate.run import source_manifest

    root = Path(__file__).resolve().parents[3]
    report = json.loads((root / "evaluation/risk-candidate-v2-results.json").read_text(encoding="utf-8"))
    original = json.loads((root / "evaluation/berka-risk-results.json").read_text(encoding="utf-8"))
    assert report["reproducibility"]["code_sha256_utf8_lf"] == source_manifest(root)
    assert report["production_activated"] is False
    assert report["release"]["allowed"] is False
    for name, comparison in report["results"].items():
        for key, value in comparison["baseline"].items():
            if key != "threshold":
                assert value == original["results"][name][key]
    validation = report["results"]["validation"]
    assert report["validation_improved"] == CandidateComparison.improved(
        validation["candidate"], validation["baseline"]
    )
    assert report["validation_release_policy_passed"] == CandidateComparison.policy(validation["candidate"])
