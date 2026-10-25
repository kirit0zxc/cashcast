"""Денежная цель резерва, строгая граница нуля и ограничения выбора."""
import unittest
import numpy as np
from .rolling_reserve_quantiles import ReservePolicy
from . import test_diverse_risk as fixtures


class ReserveQuantileTests(unittest.TestCase):
    def test_reserve_and_strict_zero_boundary(self):
        flows=np.zeros((30,2),dtype=np.int64);flows[0,1]=100;flows[1,0]=200
        for opening in (0,99,100,101):
            truth=np.column_stack([flows,opening+np.cumsum(flows[:,0]-flows[:,1])])
            self.assertEqual(ReservePolicy.target(truth,opening),100.)
        row={'opening':100,'risk18':False,'reserve_quantiles_minor':{'0.9':100.}}
        self.assertEqual(ReservePolicy.flags([row],{'mode':'alone','quantile':.9}),[False])

    def test_reject_inconsistent_target(self):
        with self.assertRaises(AssertionError):ReservePolicy.target(np.ones((30,3)),0)

    def test_early_selection_preserves_recall_and_tie_keeps31(self):
        rows=[{**r,'opening':100,'risk31':True,'reserve_quantiles_minor':{str(q):200. if r['label'] else 0. for q in ReservePolicy.QUANTILES}}
              for r in fixtures.DiverseTests().rows()]
        choice=ReservePolicy.choose(rows)['selected']
        self.assertEqual((choice['mode'],choice['quantile']),('or18',.9))
        for row in rows:row['reserve_quantiles_minor']={str(q):200. for q in ReservePolicy.QUANTILES}
        self.assertEqual(ReservePolicy.choose(rows)['selected']['mode'],'keep31')
        with self.assertRaises(ValueError):ReservePolicy.choose([{**r,'cutoff':'2026-08-31'} for r in rows])


if __name__=='__main__':unittest.main()
