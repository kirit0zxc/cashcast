"""Проверки единиц, зависимых окон и явной выборки риска в отчёте."""
import unittest
import numpy as np

from .research_audit import cash_metrics, cluster_intervals, deltas, reliability, risk_summary


class AuditTests(unittest.TestCase):
    def row(self, company='a', difference=100):
        truth=np.zeros((30,3),dtype=np.int64)
        return {'company':company,'truth':truth,'models':{'base':truth.copy(),'candidate':truth+difference}}

    def test_money_units_and_totals_are_distinct(self):
        score=cash_metrics([self.row()], 'candidate', 7)
        self.assertEqual(score['inflow_mae_rub'],1.)
        self.assertEqual(score['inflow_total_mae_rub'],7.)
        self.assertEqual(score['balance_final_mae_rub'],1.)
        self.assertEqual(score['balance_rmse_rub'],1.)

    def test_error_offsets_cancel_only_in_flow_totals(self):
        row=self.row()
        row['models']['candidate'][::2]=-100
        score=cash_metrics([row],'candidate',14)
        self.assertEqual(score['outflow_mae_rub'],1.)
        self.assertEqual(score['outflow_total_mae_rub'],0.)

    def test_balance_benchmark_does_not_claim_native_flow_forecasts(self):
        row=self.row();row['models']['benchmark75_25']=row['models']['base'].copy()
        score=cash_metrics([row],'benchmark75_25',7)
        self.assertIn('balance_mae_rub',score)
        self.assertNotIn('inflow_mae_rub',score)
        intervals=cluster_intervals([row],'candidate','benchmark75_25',7)
        self.assertEqual(set(intervals['mae_difference_rub']),{'balance'})

    def test_cluster_resamples_company_with_all_its_windows(self):
        rows=[self.row('a',100)]*3+[self.row('b',900)]
        result=cluster_intervals(rows,'candidate','base',7)
        self.assertEqual(result['unit'],'company_all_windows')
        self.assertEqual(result['mae_difference_rub']['balance']['point'],3.)
        self.assertEqual(result['mae_difference_rub']['balance']['ci95'],[1.,9.])

    def test_reliability_includes_exact_zero_and_one(self):
        result=reliability([False,True],[0.,1.])
        self.assertEqual(result['brier'],0.)
        self.assertEqual(sum(x['n'] for x in result['bins']),2)
        self.assertFalse(result['calibrated'])

    def test_undefined_relative_gain_is_not_infinite(self):
        self.assertEqual(deltas({'balance_mae_rub':1.},{'balance_mae_rub':0.}),
                         {'balance_mae_rub':{'difference_rub':1.,'change_pct':None}})

    def test_risk_or_has_confusion_but_no_claimed_probability(self):
        rows=[{'company':'a','label':True,'current':.4,'risk18':False,'scores':{'rolling_new':.03}},
              {'company':'b','label':False,'current':.6,'risk18':True,'scores':{'rolling_new':.01}}]
        result=risk_summary(rows,{'model':'rolling_new','threshold':.025})
        self.assertEqual(result['policies']['candidate21']['tp'],1)
        self.assertEqual(result['policies']['candidate21']['fp'],1)
        self.assertEqual(result['policies']['candidate21']['fn'],0)
        self.assertEqual(result['policies']['candidate21']['tn'],0)
        self.assertIsNone(result['probability_candidate21'])


if __name__=='__main__':
    unittest.main()
