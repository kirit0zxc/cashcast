"""Правило принятия фиксировано до результатов; phase gate исключает будущее."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evaluation import select_v2


def reports(maes):
    return {name: {"balance_mae_minor": value} for name, value in maes.items()}


def test_acceptance_requires_gain_stability_and_runtime():
    values = dict(baseline=150, legacy_w84=100, ewm=94, winsor=90, trend=98)
    point = reports(values)
    cutoffs = {str(index): reports({**values, "winsor": 120 if index < 2 else 10}) for index in range(3)}
    timing = {name: [1] for name in values}
    result = select_v2.choose(point, cutoffs, timing)
    assert result["method"] == "ewm"
    assert not result["gates"]["winsor"]["accepted"]
    assert not result["gates"]["trend"]["accepted"]
    timing["ewm"] = [3.1]
    assert select_v2.choose(point, cutoffs, timing)["method"] == "legacy_w84"
    point["baseline"]["balance_mae_minor"] = 80
    assert select_v2.choose(point, cutoffs, timing)["method"] == "baseline"


def test_split_stable_and_heldout_not_read_by_selection(monkeypatch):
    from app.modules.contracts import Direction, TxnDTO

    companies = [f"C{index:03}" for index in range(150)]
    heldout = [name for name in companies if select_v2.company_split(name) == "heldout_company"]
    development = [name for name in companies if name not in heldout]
    assert heldout and development
    assert all(select_v2.company_split(name) == "heldout_company" for name in heldout)
    txns = {name: [TxnDTO(name, name, select_v2.PHASE_END + timedelta(days=1), 1, Direction.IN)] for name in companies}
    balances = {name: {select_v2.PHASE_END + timedelta(days=1): 999} for name in companies}
    monkeypatch.setattr(select_v2, "load_dataset", lambda _: (txns, balances))

    class Checked(Exception):
        pass

    def check_fold(company, transactions, daily, as_of):
        assert company in development
        assert not transactions and not daily
        assert as_of in select_v2.CUTOFFS
        raise Checked

    monkeypatch.setattr(select_v2, "fold", check_fold)
    with pytest.raises(Checked):
        select_v2.run(Path("unused"))
