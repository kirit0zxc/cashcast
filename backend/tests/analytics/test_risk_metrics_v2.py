"""Метрики риска сверены с простым ручным примером и парными компаниями."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evaluation.risk_v2 import choose_threshold, paired_company_bootstrap, report, wilson


def rows():
    return [
        {"company": "a", "key": "1", "probability": 0.25, "actual": False},
        {"company": "b", "key": "2", "probability": 0.75, "actual": True, "lead_days": 10},
    ]


def test_risk_report_against_hand_calculation_and_threshold():
    result = report(rows(), 0.5)
    assert result["brier"] == 0.0625
    assert result["ece"] == 0.25
    assert result["classification"]["precision"] == result["classification"]["recall"] == 1
    assert result["classification"]["false_alarm_rate"] == 0
    assert result["true_alert_lead_days"]["mean"] == 10
    assert choose_threshold(rows())["selected"]["threshold"] == 0.5
    assert sum(value["count"] for value in result["reliability"]) == 2


def test_wilson_bootstrap_and_none_not_zero():
    assert wilson(0, 0) is None
    assert wilson(0, 10)[0] == 0
    assert wilson(10, 10)[1] == pytest.approx(1)
    first = paired_company_bootstrap(rows(), rows())
    assert first["difference_brier"] == 0 and first["ci95"] == [0, 0]
    assert paired_company_bootstrap(rows(), rows()) == first
    with pytest.raises(ValueError, match="парные"):
        paired_company_bootstrap(rows(), list(reversed(rows())))
    with pytest.raises(ValueError, match="None"):
        report([{**rows()[0], "probability": None}])
    assert report([])["brier"] is None
    assert choose_threshold([])["selected"] is None
