"""Независимые свойства протоколов29–37; только синтетика, без БД и обучения.

31: размер окна, нормировка, представление операций и маршрутизация runtime.
29/31/36/37: состав fit и фиксация выбора; известный поздний SHA29 раскрыт отдельно.
30/35/36: целые копейки и денежная идентичность после смешивания.
32/33: диагностические повторы не выбирают политику заново.
37: выигрыш общего TP/FP не скрывает ухудшение отдельного месяца.
"""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.modules.contracts import Direction, TxnDTO
from .block_flows import BlockMath
from .diverse_risk import DiverseExperiment, DiversePolicy
from .diverse_robustness import FixedDiverse
from .long_history_features import LongHistoryFeatures
from .long_history_risk import LongHistoryFeatures as TrainingFeatures, LongStudy
from .long_robustness import FixedLong
from .long_runtime import LongAddon
from .rolling_block_flows import RollingBlockMath, RollingBlockStudy
from .standalone_long_risk import StandalonePolicy, StandaloneStudy


def company(group=0, heldout=False):
    """Идентификаторы синтетические; ожидаемое разделение считаем по протоколу."""
    for i in range(10000):
        value = f"continued-synthetic-{i}"
        digest = hashlib.sha256(value.encode()).digest()
        if (digest[0] % 5 == 0) == heldout and digest[1] % 5 == group:
            return value
    raise AssertionError("Не найден синтетический идентификатор")


def risk_rows():
    base = dict(company=company(), phase="validation", cutoff="2026-01-31",
                current=.8, risk18=False, risk21=True, risk25=True, risk31=True,
                score25=.1, score31=.1)
    return [{**base, "label": label, "cat_score": score, "extended_score": score}
            for label, score in [(True, .8)] * 5 + [(False, .001)]]


def selection_hash_is_saved(output):
    """Протокол требует запись SHA, но не конкретное имя файла этой записи."""
    frozen = output / "selection-frozen.json"
    digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
    return any(digest in path.read_text("utf-8")
               for path in output.glob("*.json") if path != frozen)


class ContinuedFeatureTests(unittest.TestCase):
    def test_constant_debit_has_analytic_drawdown_and_rolling_losses(self):
        cutoff = date(2026, 8, 31)
        txns = [TxnDTO(str(i), "synthetic", cutoff - timedelta(days=i), 20000, Direction.OUT)
                for i in range(365)]
        expected = np.concatenate([
            [1, 0, 1, 0, 0, 0, 1, 1, days,
             -min(7, days), -min(7, days), -min(30, days), -min(30, days)]
            for days in (28, 84, 180, 365)])
        for transform in (LongHistoryFeatures, TrainingFeatures):
            with self.subTest(transform=transform.__module__):
                np.testing.assert_allclose(transform.make("synthetic", cutoff, txns), expected,
                                           rtol=0, atol=1e-12)

    def test_amount_scale_and_transaction_partition_do_not_change_features(self):
        cutoff = date(2026, 8, 31)
        txns = [TxnDTO(str(i), "synthetic", cutoff - timedelta(days=i),
                       200000 + 10000 * (i % 7), Direction.IN if i % 3 else Direction.OUT)
                for i in range(365)]
        split = [replace(t, id=t.id + suffix, amount_minor=amount)
                 for t in txns for suffix, amount in (("a", 1), ("b", t.amount_minor - 1))]
        scaled = [replace(t, amount_minor=t.amount_minor * 7) for t in txns]
        for transform in (LongHistoryFeatures, TrainingFeatures):
            expected = transform.make("synthetic", cutoff, txns)
            np.testing.assert_array_equal(expected, transform.make("synthetic", cutoff, split[::-1]))
            np.testing.assert_allclose(expected, transform.make("synthetic", cutoff, scaled),
                                       rtol=1e-12, atol=1e-12)

    def test_exact_365_day_boundary_only_changes_long_window(self):
        cutoff = date(2026, 8, 31)
        txns = [TxnDTO(str(i), "synthetic", cutoff - timedelta(days=i), 20000, Direction.IN)
                for i in range(365)]
        expected = LongHistoryFeatures.make("synthetic", cutoff, txns)
        outsiders = [TxnDTO("ancient", "synthetic", cutoff - timedelta(days=365), 10**12, Direction.OUT),
                     TxnDTO("future", "synthetic", cutoff + timedelta(days=1), 10**12, Direction.OUT),
                     TxnDTO("foreign", "foreign", cutoff, 10**12, Direction.OUT)]
        np.testing.assert_array_equal(expected, LongHistoryFeatures.make("synthetic", cutoff, txns + outsiders))
        changed = [replace(t, amount_minor=40000) if t.booked_on == cutoff - timedelta(days=364) else t
                   for t in txns]
        actual = LongHistoryFeatures.make("synthetic", cutoff, changed)
        np.testing.assert_array_equal(expected[:39], actual[:39])
        self.assertFalse(np.array_equal(expected[39:], actual[39:]))


class ContinuedRuntimeTests(unittest.TestCase):
    def test_actual_apply_uses_only_excluded_group_or_heldout_mean_and_past_weights(self):
        scores = [.01, .05, .11, .19, .31]
        for heldout in (False, True):
            for group in range(5):
                for base_warning in (False, True):
                    account = company(group, heldout)
                    loaded = []

                    def booster(model_file):
                        name = Path(model_file).name
                        self.assertTrue(name.startswith("past-"), "Загружены будущие веса")
                        selected = int(name.split("-")[1])
                        loaded.append(selected)
                        return SimpleNamespace(predict=lambda x, **_: np.array([scores[selected]]))

                    data = SimpleNamespace(account_id=account, horizon_days=30,
                                           planned_events=[], recurrences=[], scenario=[])
                    base = {"candidate": "cashcast-research-18", "status": "research_only",
                            "as_of": "2026-02-15", "current": [[100, 200, -100]],
                            "risk": {"new_gap_warning": base_warning, "probability_any_negative": None}}
                    original = deepcopy(base)
                    manifest = {"threshold": .1, "models": {
                        "2026-01-31": [f"past-{i}" for i in range(5)],
                        "2026-02-28": [f"future-{i}" for i in range(5)]}}
                    with patch.dict(sys.modules, {"lightgbm": SimpleNamespace(Booster=booster)}), \
                            patch.object(LongAddon, "features", return_value=(data, np.zeros((1, 86)))):
                        result = LongAddon.apply(base, {"input": {"as_of": base["as_of"]}}, manifest, Path("."))
                    expected = float(np.mean(scores)) if heldout else scores[group]
                    self.assertEqual(loaded, list(range(5)) if heldout else [group])
                    self.assertAlmostEqual(result["risk_extension"]["uncalibrated_score"], expected)
                    self.assertEqual(result["risk"]["new_gap_warning"], base_warning or expected >= .1)
                    self.assertEqual(result["risk_extension"]["training_cutoff"], "2026-01-31")
                    self.assertEqual(base, original)
                    self.assertEqual(result["current"], original["current"])
                    self.assertEqual(result["risk18"], original["risk"])
                    self.assertIsNone(result["risk"]["probability_any_negative"])


class ContinuedTrainingTests(unittest.TestCase):
    @staticmethod
    def rows():
        rows = []
        for group in range(5):
            for heldout in (False, True):
                for age, opening, label in ((37, 0, False), (38, 0, True), (36, 0, True), (37, -1, True)):
                    marker = len(rows) + 1
                    cutoff = date(2026, 1, 31) - timedelta(days=age)
                    rows.append(dict(company=company(group, heldout), as_of=str(cutoff), cutoff=str(cutoff),
                                     opening=opening, label=label, features=np.full(86, marker, dtype=float),
                                     base_features=np.full(93, marker, dtype=float), scale=100.,
                                     truth=np.full((30, 3), 100, dtype=np.int64)))
        return rows

    def test_actual_fit_calls_respect_company_time_and_opening_rules(self):
        """Перехватываем вход fit, а не только отдельно вызываем predicate eligible."""
        class Recorder:
            fits = []
            saved = {}

            def __init__(self, **_):
                pass

            def fit(self, x, y, sample_weight):
                self.x = np.asarray(x).copy()
                self.fits.append(self.x)

            def save_model(self, path):
                self.saved[path] = self.x

            def load_model(self, path):
                self.x = self.saved[path]

            def predict(self, x, **_):
                return np.zeros(len(x))

            def predict_proba(self, x, **_):
                return np.full((len(x), 2), .5)

        for study_type, module, flow in (
                (RollingBlockStudy, "rolling_block_flows", True),
                (StandaloneStudy, "diverse_risk", False)):
            with self.subTest(study=study_type.__name__), tempfile.TemporaryDirectory() as temporary:
                Recorder.fits = []
                Recorder.saved = {}
                study = object.__new__(study_type)
                study.output = Path(temporary)
                study.audits = {}
                rows = self.rows()
                if flow:
                    study.training_rows, study.group_models = rows, {}
                else:
                    study.train, study.models = rows, {}
                fake = SimpleNamespace(CatBoostRegressor=Recorder, CatBoostClassifier=Recorder)
                with patch.dict(sys.modules, {"catboost": fake}), \
                        patch(f"evaluation.liquidity_risk.{module}.digest", return_value="synthetic-sha"), \
                        redirect_stdout(io.StringIO()):
                    study.train_cutoff("2026-01-31")
                self.assertEqual(len(Recorder.fits), 10 if flow else 5)
                for excluded in range(5):
                    expected = {int(r["features"][0]) for r in rows
                                if hashlib.sha256(r["company"].encode()).digest()[0] % 5 != 0
                                and hashlib.sha256(r["company"].encode()).digest()[1] % 5 != excluded
                                and date.fromisoformat(r["as_of"]) <= date(2025, 12, 25)
                                and (flow or r["opening"] >= 0)}
                    for channel in range(2 if flow else 1):
                        fitted = Recorder.fits[excluded * (2 if flow else 1) + channel]
                        self.assertEqual(set(fitted[:, 0].astype(int)), expected)

    def test_targets_cannot_change_features_or_training_weights(self):
        rows = self.rows()[:2]
        before = deepcopy(rows)
        x, y, weights = RollingBlockMath.training(rows)
        changed = deepcopy(rows)
        changed[0]["truth"][:, :2] *= 1000000
        x2, y2, weights2 = RollingBlockMath.training(changed)
        np.testing.assert_array_equal(x, x2)
        np.testing.assert_array_equal(weights, weights2)
        self.assertFalse(np.array_equal(y, y2))
        for old, original in zip(rows, before, strict=True):
            np.testing.assert_array_equal(old["truth"], original["truth"])

    def test_standalone_predict_uses_excluded_group_for_each_development_company(self):
        study = object.__new__(StandaloneStudy)
        scores = [.01, .05, .11, .19, .31]
        study.models = {"2026-01-31": {g: SimpleNamespace(
            predict_proba=lambda x, value=scores[g], **_: np.tile([1 - value, value], (len(x), 1)))
            for g in range(5)}}
        rows = [dict(company=company(g, heldout), cutoff="2026-01-31", features=[0.])
                for heldout in (False, True) for g in range(5)]
        with patch.object(study, "train_cutoff"):
            study.predict(rows)
        np.testing.assert_allclose([r["cat_score"] for r in rows], scores + [np.mean(scores)] * 5)


class ContinuedMoneyTests(unittest.TestCase):
    def test_random_block_mixes_preserve_integer_cash_identity_and_inputs(self):
        rng = np.random.default_rng(20261025)
        for _ in range(30):
            current = rng.integers(0, 100000, (30, 3), dtype=np.int64)
            current[:7, 0] = 0
            predicted = rng.uniform(-2, 10, (3, 2))
            row = dict(fallback=False, opening=-4321, models={"current": current})
            original = current.copy()
            for alpha in (.25, .5, 1.):
                result = BlockMath.predict(row, predicted, 173., alpha)
                self.assertTrue(np.issubdtype(result.dtype, np.integer))
                self.assertTrue(np.all(result[:, :2] >= 0))
                np.testing.assert_array_equal(result[:, 2], row["opening"] + np.cumsum(result[:, 0] - result[:, 1]))
                if alpha == 1.:
                    for i, (start, end) in enumerate(((0, 7), (7, 14), (14, 30))):
                        expected = [round(max(0., value) * 173. * (end - start)) for value in predicted[i]]
                        np.testing.assert_array_equal(result[start:end, :2].sum(axis=0), expected)
                np.testing.assert_array_equal(current, original)

    def test_allocation_preserves_full_money_boundary_and_profile_units(self):
        rng = np.random.default_rng(20261025)
        for total in (0, 1, 17, 10**12, 9_000_000_000_000_000):
            for _ in range(25):
                profile = rng.integers(0, 100000, 16)
                allocated = BlockMath.allocate(total, profile)
                self.assertEqual(sum(map(int, allocated)), total)
                self.assertTrue(np.all(allocated >= 0))
                # Степень двойки меняет единицы профиля без ошибки округления float.
                np.testing.assert_array_equal(allocated, BlockMath.allocate(total, profile * 8))


class ContinuedSelectionTests(unittest.TestCase):
    def test_total_tp_gain_cannot_hide_lost_month(self):
        rows = risk_rows()
        rows[0].update(cutoff="2026-01-31", cat_score=0., score31=0., risk31=True)
        for row in rows[1:]:
            row.update(cutoff="2026-02-28", risk31=not row["label"],
                       cat_score=.8 if row["label"] else 0., score31=.8 if row["label"] else 0.)
        choice = StandalonePolicy.choose(rows)
        self.assertEqual(choice["selected"]["mode"], "keep31")
        candidate = next(t for t in choice["trials"] if t["mode"] == "cat" and t["threshold"] == .005)
        self.assertGreater(candidate["metrics"]["tp"], choice["selected"]["metrics"]["tp"])
        self.assertFalse(candidate["eligible"])

    def test_total_fp_gain_cannot_hide_worse_month(self):
        rows = risk_rows()
        for row in rows:
            row.update(cutoff="2026-02-28", cat_score=.8 if row["label"] else 0., score31=0.)
        rows.extend([{**rows[-1], "label": False, "risk31": True, "cat_score": 0.} for _ in range(4)])
        rows.append({**rows[-1], "cutoff": "2026-01-31", "risk31": False, "cat_score": 1., "score31": 1.})
        choice = StandalonePolicy.choose(rows)
        self.assertEqual(choice["selected"]["mode"], "keep31")
        candidate = next(t for t in choice["trials"] if t["mode"] == "cat" and t["threshold"] == .005)
        self.assertLess(candidate["metrics"]["fp"], choice["selected"]["metrics"]["fp"])
        self.assertFalse(candidate["eligible"])

    def test_heldout_or_late_row_cannot_enter_standalone_selection(self):
        for replacement in ({"company": company(0, True)}, {"cutoff": "2026-07-31"}, {"phase": "other_early"}):
            rows = risk_rows()
            rows[-1].update(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                StandalonePolicy.choose(rows)

    def test_insufficient_positive_support_and_ties_keep31(self):
        rows = risk_rows()
        self.assertEqual(StandalonePolicy.choose(rows[1:])["selected"]["mode"], "keep31")
        for row in rows:
            row.update(cat_score=1., score31=1.)
        self.assertEqual(StandalonePolicy.choose(rows)["selected"]["mode"], "keep31")

    def test_risk_runs_save_selection_and_hash_before_any_late_prediction(self):
        class LateReached(Exception):
            pass

        for study_type in (LongStudy, StandaloneStudy):
            with self.subTest(study=study_type.__name__), tempfile.TemporaryDirectory() as temporary:
                study = object.__new__(study_type)
                study.output = Path(temporary)
                study.control = risk_rows() + [{**risk_rows()[0], "phase": "late_development", "cutoff": "2026-07-31"}]
                seen = []

                def predict(rows):
                    seen.append([r["phase"] for r in rows])
                    if any(r["phase"] == "late_development" for r in rows):
                        self.assertTrue(selection_hash_is_saved(study.output),
                                        "SHA раннего выбора не сохранён до позднего predict")
                        raise LateReached

                with patch.object(study, "predict", side_effect=predict), redirect_stdout(io.StringIO()), \
                        self.assertRaises(LateReached):
                    study.run()
                self.assertEqual(seen, [["validation"] * 6, ["late_development"]])

    def test_historical29_freezes_selection_but_records_hash_only_at_completion(self):
        """Известное ограничение B-CONTINUED-20261025.md, не свидетельство pre-late SHA."""
        with tempfile.TemporaryDirectory() as temporary:
            study = object.__new__(DiverseExperiment)
            study.output, study.models = Path(temporary), {}
            study.control = risk_rows() + [{**risk_rows()[0], "phase": "late_development", "cutoff": "2026-07-31"}]
            hashes_before_late = []

            def predict(rows):
                if any(r["phase"] == "late_development" for r in rows):
                    frozen = study.output / "selection-frozen.json"
                    self.assertIn("selected", json.loads(frozen.read_text("utf-8")))
                    self.assertFalse(selection_hash_is_saved(study.output))
                    hashes_before_late.append(hashlib.sha256(frozen.read_bytes()).hexdigest())

            with patch.object(study, "predict", side_effect=predict), redirect_stdout(io.StringIO()):
                study.run()
            completed = json.loads((study.output / "completed.json").read_text("utf-8"))
            self.assertEqual(hashes_before_late, [completed["selection_sha256"]])
            self.assertEqual(hashlib.sha256((study.output / "selection-frozen.json").read_bytes()).hexdigest(),
                             completed["selection_sha256"])

    def test_rolling_flow_run_freezes_selection_before_late_inference(self):
        class LateReached(Exception):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            study = object.__new__(RollingBlockStudy)
            study.output = Path(temporary)
            truth = np.full((30, 3), 100, dtype=np.int64)
            row = dict(company=company(), cutoff="2026-01-31", truth=truth,
                       models={"current": truth * 2, **{f"block{a}": truth.copy() for a in (.25, .5, 1.)}})

            def infer(phase):
                if phase == "validation":
                    return [row]
                self.assertTrue(selection_hash_is_saved(study.output),
                                "SHA раннего выбора не сохранён до позднего infer")
                raise LateReached

            with patch.object(study, "train"), patch.object(study, "infer", side_effect=infer), \
                    redirect_stdout(io.StringIO()), self.assertRaises(LateReached):
                study.run()

    def test_robustness_runs_use_fixed_policies_without_selector(self):
        for study_type in (FixedDiverse, FixedLong):
            with self.subTest(study=study_type.__name__), tempfile.TemporaryDirectory() as temporary:
                study = object.__new__(study_type)
                study.output = Path(temporary)
                study.control = risk_rows()
                with patch.object(study, "predict"), patch.object(DiversePolicy, "choose", side_effect=AssertionError("Повторный выбор")):
                    if study_type is FixedDiverse:
                        reference = study.output / "reference"
                        reference.mkdir()
                        (reference / "selection-frozen.json").write_text(json.dumps({"selected": {"mode": "mean50", "threshold": .05}}))
                        report = study.run_fixed(reference)
                    else:
                        report = study.run_fixed()
                key = "selected29" if study_type is FixedDiverse else "selected31"
                self.assertEqual(report["total"][key]["tp"], 5)


if __name__ == "__main__":
    unittest.main()
