"""Goldens получены до изменения правил, от исходной версии B4/331b6f2."""

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from app.modules.contracts import ScenarioChange
from app.modules.forecasting.legacy_v1.seasonal import SeasonalForecastService as FrozenSeasonal
from tests.analytics.test_seasonal import history, recurring_input

INPUTS = [
    history(),
    history(7),
    recurring_input(),
    replace(history(), scenario=[ScenarioChange("reduce_irregular_inflow", factor=0.5)]),
]


@pytest.mark.parametrize("window", [28, 56, 84])
@pytest.mark.parametrize("index", range(len(INPUTS)))
def test_frozen_matches_original_b4_golden(window, index):
    golden = json.loads((Path(__file__).parent / "fixtures/legacy-v1-golden.json").read_text(encoding="utf-8"))
    result = FrozenSeasonal(paths=golden["paths"], lookback_days=window).run(INPUTS[index])
    serialized = json.dumps(asdict(result), sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    assert hashlib.sha256(serialized.encode()).hexdigest() == golden["golden"][f"{window}:{index}"]


def test_frozen_manifest_and_independence_from_new_rules(monkeypatch):
    from app.modules.categorization.service import RuleCategorizer
    from app.modules.forecasting import legacy_v1

    folder = Path(legacy_v1.__file__).parent
    manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, expected_hash in manifest["files"].items():
        assert hashlib.sha256((folder / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected_hash
    expected = FrozenSeasonal(paths=20).run(history())

    def broken_new_rules(*_args):
        raise AssertionError("new rules must not affect frozen version")

    monkeypatch.setattr(RuleCategorizer, "categorize", broken_new_rules)
    assert FrozenSeasonal(paths=20).run(history()) == expected
