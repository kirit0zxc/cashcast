"""Проверки целевой величины резерва и причинных входов модели риска."""
import sys
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"backend"))
from app.modules.contracts import Direction, TxnDTO
from evaluation.fallback_model import test_model as fixtures
from .model import ALPHAS, ReserveFeatures, ReserveModel


class RiskTests(unittest.TestCase):
    def test_reserve_sees_loss_before_later_income(self):
        self.assertEqual(ReserveFeatures.reserve([[0,100],[200,0]]),100)

    def test_earlier_income_covers_later_loss(self):
        self.assertEqual(ReserveFeatures.reserve([[200,0],[0,100]]),0)

    def test_random_identity_and_zero_boundary(self):
        rng=np.random.default_rng(19)
        for _ in range(100):
            flows=rng.integers(0,10000,(30,2))
            reserve=ReserveFeatures.reserve(flows)
            for opening in (0,reserve,max(0,reserve-1),reserve+1):
                balance=opening+np.cumsum(flows[:,0]-flows[:,1])
                self.assertEqual(opening<reserve,bool(np.any(balance<0)))

    def test_probability_decreases_as_opening_grows(self):
        values=np.array([0,0,0,1,2,5,10,15,25])
        probabilities=[ReserveModel.probability(values,opening) for opening in np.linspace(0,40,81)]
        self.assertTrue(all(a>=b for a,b in zip(probabilities,probabilities[1:])))
        self.assertTrue(all(0<=p<=1 for p in probabilities))

    def test_exact_zero_uses_right_cdf(self):
        self.assertAlmostEqual(ReserveModel.probability(np.zeros(len(ALPHAS)),0),.01)

    def test_tail_is_not_claimed_certain(self):
        self.assertGreater(ReserveModel.probability(np.arange(9),1e9),0)

    def test_future_records_do_not_change_features(self):
        data=fixtures.ModelTests.example()
        future=TxnDTO("unknown",data.account_id,data.as_of+timedelta(days=1),10**10,Direction.OUT)
        a=ReserveFeatures.make(data)
        b=ReserveFeatures.make(replace(data,txns=data.txns+[future]))
        np.testing.assert_array_equal(a[0],b[0])
        np.testing.assert_array_equal(a[3],b[3])

    def test_feature_finite_and_seed_free(self):
        data=fixtures.ModelTests.example()
        a=ReserveFeatures.make(data)
        self.assertTrue(np.isfinite(a[0]).all())
        np.testing.assert_array_equal(a[0],ReserveFeatures.make(replace(data,seed=100))[0])

    def test_zero_pinball_for_exact_quantiles(self):
        self.assertEqual(ReserveModel.pinball([5,8],np.array([[5]*9,[8]*9])),0)

    def test_bad_shape_rejected(self):
        with self.assertRaises(ValueError):
            ReserveFeatures.reserve([])


if __name__ == "__main__":
    unittest.main()
