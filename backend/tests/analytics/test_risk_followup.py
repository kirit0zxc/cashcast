"""Калибровка, честный отказ от слабого порога и неопределённость по счетам."""

import sys
from pathlib import Path
from statistics import mean

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evaluation.risk_followup.policy import InterceptCalibrator, choose_operating_point, reliability
from evaluation.risk_followup.uncertainty import account_bootstrap


def test_intercept_matches_fit_prevalence_and_preserves_order():
    labels = [1] * 20 + [0] * 980
    scores = [0.2] * 10 + [0.1] * 990
    fit = InterceptCalibrator.fit(labels, scores)
    assert fit is not None
    transformed = fit.transform(scores)
    assert mean(transformed) == pytest.approx(0.02, abs=1e-10)
    assert transformed[0] > transformed[-1]
    assert fit.intercept < 0


@pytest.mark.parametrize("labels", [[0] * 1000, [1] * 1000, [1] * 9 + [0] * 991, [1] * 20 + [0] * 20])
def test_calibration_not_available_with_insufficient_classes(labels):
    assert InterceptCalibrator.fit(labels, [0.1] * len(labels)) is None


@pytest.mark.parametrize("scores", [[float("nan")], [float("inf")], [-0.1], [1.1], []])
def test_invalid_probabilities_rejected(scores):
    with pytest.raises(ValueError):
        reliability([0], scores)


def test_reliability_covers_zero_one_and_boundaries_once():
    bins = reliability([0, 1, 1, 0], [0, 1, 0.005, 0.001])
    assert sum(b["count"] for b in bins) == 4
    assert bins[0]["count"] == bins[1]["count"] == bins[2]["count"] == bins[-1]["count"] == 1
    assert bins[-1]["observed_frequency"] == 1


def test_perfect_operating_point_passes_and_tie_uses_higher_threshold():
    result = choose_operating_point([1] * 20 + [0] * 1980, [0.6] * 20 + [0.001] * 1980, 0.01)
    assert result["selected"]["threshold"] == 0.5
    assert result["selected"]["precision"] == result["selected"]["recall"] == 1


def test_bad_or_unidentifiable_threshold_returns_none_not_one():
    result = choose_operating_point([1] * 20 + [0] * 1980, [0.1] * 2000, 0.01)
    assert result["selected"] is None
    assert result["reason"] == "no_threshold_meets_policy"
    assert choose_operating_point([0] * 100, [0.1] * 100, 0.01)["selected"] is None


def test_bootstrap_keeps_entire_account_and_does_not_zero_undefined_recall():
    result = account_bootstrap(["a", "a", "b", "b"], [1, 1, 0, 0], [0.9, 0.9, 0.1, 0.1], 0.5, 0.5, repetitions=100)
    assert result["unit"] == "account" and result["accounts"] == 2
    assert result["recall"]["ci95"] == [1, 1]
    assert result["recall"]["undefined_repetitions"] > 0
    assert result["recall"]["valid_repetitions"] + result["recall"]["undefined_repetitions"] == 100
    assert result["brier_minus_constant"]["ci95"] == pytest.approx([-0.24, -0.24])
    assert result == account_bootstrap(
        ["a", "a", "b", "b"], [1, 1, 0, 0], [0.9, 0.9, 0.1, 0.1], 0.5, 0.5, repetitions=100
    )


def test_bootstrap_no_alert_is_not_zero_precision():
    result = account_bootstrap(["a", "b"], [0, 0], [0.01, 0.01], 0.5, 0.1, repetitions=20)
    assert result["precision"]["ci95"] is None
    assert result["precision"]["undefined_repetitions"] == 20
    with pytest.raises(ValueError):
        account_bootstrap([], [], [], 0.5, 0.1)
