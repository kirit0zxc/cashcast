"""Проверка выбора ранних весов и сопоставимости сторонних прогнозов."""
import unittest

import numpy as np

from .peer_specialists import PeerPolicy, PeerStudy


class PeerTests(unittest.TestCase):
    @staticmethod
    def row():
        return dict(company='C001',cutoff='2026-04-30',truth=np.zeros((30,3)),
                    current=np.ones((30,3))*100,fixed=np.ones((30,3))*100,peer=np.ones((30,3))*50,
                    label=False,probability=.1,risk18=False,peer_classifier=.01,peer_quantile=.01)

    def test_better_early_expert_is_selected(self):
        rows=[self.row()]
        self.assertEqual(PeerPolicy.choose(rows,2)['selected']['weight'],1.)

    def test_late_data_cannot_choose_weights_or_risk(self):
        row={**self.row(),'cutoff':'2026-08-31'}
        with self.assertRaises(ValueError):PeerPolicy.choose([row],2)
        with self.assertRaises(ValueError):PeerPolicy.choose_risk([row])

    def test_weight_domain(self):
        with self.assertRaises(ValueError):PeerPolicy.mix([1],[2],-.25)
        np.testing.assert_array_equal(PeerPolicy.mix([1],[3],.5),[2])

    def test_total_error_is_signed_sum_before_absolute(self):
        r=self.row();r['current'][:]=0;r['current'][:2,0]=[100,-100]
        metrics=PeerPolicy.metrics([r],'current',0)
        self.assertEqual(metrics['total_mae7'],0)
        self.assertGreater(metrics['mae7'],0)

    def test_duplicate_horizon_is_rejected(self):
        with self.assertRaises(ValueError):PeerStudy.daily([{'h':1}]*30,{})

    def test_mismatched_fact_is_rejected(self):
        rr=[]
        for h in range(1,31):
            r={'h':h}
            for prefix,keys in [('actual',('inflow','outflow','balance')),
                                ('current_2_1_w84',('inflow','outflow','p50')),
                                ('lightgbm_global',('inflow','outflow','p50'))]:
                for k in keys:r[f'{prefix}_{k}_rub']=0
            rr.append(r)
        original={'truth':np.ones((30,3)),'models':{'current':np.zeros((30,3))}}
        with self.assertRaises(AssertionError):PeerStudy.daily(rr,original)

    def test_risk_guard_does_not_trade_away_existing_tp(self):
        rows=[{**self.row(),'label':True,'risk18':True,'probability':.7},
              {**self.row(),'label':True,'risk18':False,'peer_classifier':.1},
              {**self.row(),'label':False,'risk18':False,'peer_classifier':.2}]
        choice=PeerPolicy.choose_risk(rows)['selected']
        # Новая тревога нарушает лимит ложных тревог, сохраняем базовый детектор.
        self.assertEqual(choice['source'],'keep')


if __name__=='__main__':unittest.main()
