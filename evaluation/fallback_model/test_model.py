"""Изолированные проверки нового кандидата, без подключения к БД."""

import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, TxnDTO
from app.modules.forecasting.service import DEFAULT_MODEL_VERSION
from .data import Dataset
from .features import DirectCandidate, DirectFeatures
from .metrics import Score
from .uncertainty import ErrorTrajectories


class ModelTests(unittest.TestCase):
    @staticmethod
    def example():
        start = date(2025, 1, 1)
        txns, balances = [], []
        balance = 100000
        for i in range(84):
            day = start + timedelta(days=i)
            amount = 100 + 10 * day.weekday()
            txns.append(TxnDTO(str(i), "account", day, amount, Direction.IN))
            balance += amount
            balances.append(DailyBalanceDTO("account", day, balance))
        return ForecastInput("account", day, 30, balance, 42, txns, balances, [])

    def test_future_transactions_and_balances_do_not_change_features(self):
        data = self.example()
        polluted = replace(data, txns=data.txns + [TxnDTO("future", "account", data.as_of + timedelta(days=1), 10**10, Direction.OUT)],
                           daily_balances=data.daily_balances + [DailyBalanceDTO("account", data.as_of + timedelta(days=1), -10**10)])
        a, scale, _ = DirectFeatures.make(data)
        b, other_scale, _ = DirectFeatures.make(polluted)
        np.testing.assert_array_equal(a, b)
        self.assertEqual(scale, other_scale)

    def test_other_account_cannot_influence_features(self):
        data = self.example()
        polluted = replace(data, txns=data.txns + [TxnDTO("other", "other", data.as_of, 10**10, Direction.OUT)])
        np.testing.assert_array_equal(DirectFeatures.make(data)[0], DirectFeatures.make(polluted)[0])

    def test_same_past_has_prefix_consistency(self):
        data = self.example()
        np.testing.assert_array_equal(DirectFeatures.make(replace(data, horizon_days=7))[0], DirectFeatures.make(data)[0][:7])

    def test_scale_is_equivariant_above_floor(self):
        data = self.example()
        doubled = replace(data, txns=[replace(t, amount_minor=2*t.amount_minor) for t in data.txns],
                          daily_balances=[replace(b, closing_balance_minor=2*b.closing_balance_minor) for b in data.daily_balances],
                          opening_balance_minor=2*data.opening_balance_minor)
        x, scale, _ = DirectFeatures.make(data)
        y, scale2, _ = DirectFeatures.make(doubled)
        np.testing.assert_allclose(x, y)
        self.assertEqual(scale2, 2*scale)

    def test_cumulative_projection_preserves_money(self):
        class FakeModel:
            def predict(self, x):
                return np.array([[1 if i % 2 else -5, 0.5] for i in range(len(x))])
        candidate = DirectCandidate()
        candidate.model = FakeModel()
        data = self.example()
        flows, balances, _, _ = candidate.predict(data)
        self.assertTrue((flows >= 0).all())
        np.testing.assert_array_equal(balances, data.opening_balance_minor + np.cumsum(flows[:, 0] - flows[:, 1]))

    def test_no_probability_claim_from_point_classification(self):
        result = Score.classification([False, False], [False, False])
        self.assertEqual(result["accuracy"], 1)
        self.assertIsNone(result["recall"])
        self.assertNotIn("roc_auc", result)

    def test_confusion_matrix_and_units(self):
        result = Score.classification([True, False, True, False], [True, True, False, False])
        self.assertEqual([result[k] for k in ("tp", "fp", "fn", "tn")], [1, 1, 1, 1])
        self.assertEqual(result["f1"], 0.5)

    def test_training_split_is_stable(self):
        import hashlib
        for name in ("a", "b", "test-company"):
            self.assertEqual(Dataset.heldout(name), hashlib.sha256(name.encode()).digest()[0] % 5 == 0)

    def test_default_model_unchanged(self):
        self.assertEqual(DEFAULT_MODEL_VERSION, "seasonal-estimated-2.1-w84")

    def test_short_history_finite_features(self):
        data = self.example()
        short = replace(data, txns=data.txns[-7:], daily_balances=data.daily_balances[-7:])
        x, scale, quality = DirectFeatures.make(short)
        self.assertTrue(np.isfinite(x).all())
        self.assertGreater(scale, 0)
        self.assertLess(quality.history_days, 28)

    def test_joint_paths_union_exceeds_each_daily_probability(self):
        paths = np.random.default_rng(42).normal(size=(200, 30)).cumsum(axis=1)
        estimate = ErrorTrajectories(paths).predict(np.ones(30), 1)
        self.assertGreaterEqual(estimate["union"], max(estimate["daily"]))
        self.assertTrue((estimate["lower"] <= estimate["upper"]).all())

    def test_bad_path_shape_rejected(self):
        with self.assertRaises(ValueError):
            ErrorTrajectories(np.ones((200, 29)))

    def test_local_adapter_historical_data_uses_current(self):
        from .adapter import LocalFallbackService
        result = LocalFallbackService(Path("absent-test-artifacts")).run(self.example())
        self.assertEqual(result.model_version, DEFAULT_MODEL_VERSION)
        self.assertFalse(result.details["local_candidate"]["used"])


if __name__ == "__main__":
    unittest.main()
