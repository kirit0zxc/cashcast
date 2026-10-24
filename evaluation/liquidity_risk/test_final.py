"""Проверки неизменности тревог и безопасного локального сравнения."""
import unittest
from dataclasses import replace

import numpy as np

from evaluation.fallback_model import test_model as fixtures
from .chronos_alert import QuantileWarning
from .local_compare import OfflineComparison
from .risk_scale import RiskScale


class FakeTensor:
    def __init__(self, values): self.values = values
    def detach(self): return self
    def cpu(self): return self
    def numpy(self): return self.values


class FakePipeline:
    def __init__(self, values=None):
        self.values = np.tile([-.5, 0., .5], (1, 30, 1)) if values is None else values
        self.calls = []

    def predict_quantiles(self, inputs, **kwargs):
        self.calls.append((inputs, kwargs))
        return [FakeTensor(self.values)], None


class FinalTests(unittest.TestCase):
    def test_scale_preserves_decisions_including_boundary(self):
        p = np.r_[0., .5, 1., np.linspace(0, 1, 101)]
        scale = RiskScale(-4.273514118203247)
        np.testing.assert_array_equal(p >= .5, scale.predict(p) >= scale.predict(.5))
        self.assertTrue(np.all(np.isfinite(scale.predict(p))))

    def test_scale_fit_matches_smoothed_prior(self):
        scale, prior = RiskScale.fit([.1, .4, .8, .9], [0, 0, 0, 1])
        self.assertAlmostEqual(float(np.mean(scale.predict([.1, .4, .8, .9]))), prior)

    def test_zero_is_not_negative_warning(self):
        self.assertFalse(QuantileWarning.triggered([0, 2]))
        self.assertTrue(QuantileWarning.triggered([2, -.01]))

    def test_quantile_warning_is_monotone(self):
        quantiles = np.sort(np.random.default_rng(24).normal(size=(30, 5)), axis=1)
        flags = [QuantileWarning.triggered(quantiles[:, i]) for i in range(5)]
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_warning_does_not_claim_probability(self):
        result = QuantileWarning.summarize([
            {"opening": 0, "current_probability": .1, "label": False, "warnings": {"0.1": True}},
            {"opening": 0, "current_probability": None, "label": True, "warnings": {"0.1": False}},
        ], .1)
        self.assertEqual(result["n"], 1)
        self.assertIsNone(result["probability"])

    @staticmethod
    def service(pipeline=None):
        return OfflineComparison({"id": "local-test", "revision": "test"}, pipeline or FakePipeline())

    def test_comparison_keeps_models_and_probabilities_separate(self):
        data = fixtures.ModelTests.example()
        pipeline = FakePipeline()
        result = self.service(pipeline).run(data)
        candidate = result["candidate"]
        self.assertEqual(candidate["status"], "research_only")
        self.assertEqual(len(candidate["points"]), 30)
        self.assertNotIn("inflow_minor", candidate["points"][0])
        self.assertIsNone(candidate["probability_any_negative"])
        self.assertFalse(candidate["release_allowed"])
        self.assertFalse(pipeline.calls[0][1]["cross_learning"])

    def test_unsupported_horizon_never_runs_candidate(self):
        pipeline = FakePipeline()
        result = self.service(pipeline).run(replace(fixtures.ModelTests.example(), horizon_days=7))
        self.assertEqual(result["candidate"]["status"], "unavailable")
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(len(result["current"]["points"]), 7)

    def test_corrupt_model_outputs_rejected(self):
        for values in (np.full((1, 30, 3), np.nan), np.ones((1, 30, 3))*1e40, np.zeros((1, 7, 3))):
            with self.subTest(shape=values.shape), self.assertRaises(ValueError):
                self.service(FakePipeline(values)).run(fixtures.ModelTests.example())


if __name__ == "__main__": unittest.main()
