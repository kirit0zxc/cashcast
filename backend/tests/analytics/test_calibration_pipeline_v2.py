"""Фазы/union/перенос: check не переобучает fit и не подбирает метод по чужим компаниям."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evaluation import calibrate_v2

from app.modules.forecasting.v2.calibration import CalibrationModel


def record(company="a", *, split="development", actual=False, opening_negative=False):
    return {
        "company": company,
        "key": "2026-06-30",
        "split": split,
        "cohort": "established",
        "opening_negative": opening_negative,
        "horizon_raw": 0.9,
        "daily_raw": [0.8],
        "daily_actual": [actual],
        "horizon_actual": actual,
        "lead_days": 1 if actual and not opening_negative else None,
    }


def fitted():
    models = {
        "raw": CalibrationModel("raw"),
        "constant": CalibrationModel("constant", (0.1,)),
        "logit_intercept": CalibrationModel("logit_intercept", (0.0,)),
        "pava": CalibrationModel("pava", (0.2,) * 6),
    }
    return {"horizon": models, "daily": models}


def test_union_applied_after_mapping_and_not_before():
    result = calibrate_v2.transform(
        [record()], CalibrationModel("constant", (0.1,)), CalibrationModel("constant", (0.6,))
    )
    assert result["horizon"][0]["probability"] == result["daily"][0]["probability"] == 0.6
    assert result["union_adjusted_folds"] == 1


def test_heldout_can_reject_but_never_choose_another_model():
    fit = [record(str(index)) for index in range(100)]
    check = [record(str(index)) for index in range(60)]
    before = calibrate_v2.select_configuration(fit, check, fitted())
    heldout = [record("heldout", split="heldout_company", actual=True)]
    after = calibrate_v2.select_configuration(fit, check + heldout, fitted())
    assert before["chosen"] == after["chosen"] == {"horizon": "constant", "daily": "constant"}
    assert not after["check_after_union"]["heldout_company"]["horizon"]["passed"]
    assert not after["probability_verified"]


def test_new_gap_support_and_descriptive_cohorts_are_separate():
    records = [record("existing", actual=True, opening_negative=True), record("new", actual=True)]
    config = {"chosen": {"horizon": "constant", "daily": "constant"}, "threshold": {"selected": {"threshold": 0.05}}}
    result = calibrate_v2.starting_balance_audit(records, fitted(), config)
    assert result["development"]["already_negative"]["persistence"]["horizon"]["brier"] == 0
    assert result["development"]["nonnegative_opening"]["persistence"]["horizon"]["brier"] == 1
    assert result["development"]["already_negative"]["selected"]["horizon"]["true_alert_lead_days"]["count"] == 0
    assert not calibrate_v2.support(records, records, "horizon")["passed"]


def test_fit_phase_cannot_read_future_target_coverage_or_heldout_company(monkeypatch):
    from app.modules.contracts import Direction, TxnDTO

    end = calibrate_v2.PHASES["fit"][1]
    companies = [f"C{index:03}" for index in range(150)]
    txns = {company: [TxnDTO(company, company, end + timedelta(days=1), 1, Direction.IN)] for company in companies}
    balances = {company: {end + timedelta(days=1): 999} for company in companies}

    class Checked(Exception):
        pass

    def check_fold(company, transactions, daily, as_of):
        assert calibrate_v2.company_split(company) == "development"
        assert not transactions and not daily
        assert as_of in calibrate_v2.PHASES["fit"][0]
        raise Checked

    monkeypatch.setattr(calibrate_v2, "fold", check_fold)
    with pytest.raises(Checked):
        calibrate_v2.collect(txns, balances, "fit", None)
