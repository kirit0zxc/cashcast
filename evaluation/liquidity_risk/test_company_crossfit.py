"""Разделение компаний и времени, равный вес и ранние ограничения выбора."""
from datetime import date
import unittest
import numpy as np

from evaluation.fallback_model.data import Dataset
from .company_crossfit import CrossfitPolicy, CrossfitExperiment


class CrossfitTests(unittest.TestCase):
    @staticmethod
    def company(heldout=False):
        return next('synthetic'+str(i) for i in range(100) if Dataset.heldout('synthetic'+str(i))==heldout)

    def test_training_excludes_heldout_group_and_unconfirmed_future(self):
        company=self.company(); group=CrossfitPolicy.group(company)
        row={'company':company,'opening':0,'as_of':'2025-11-24'}
        self.assertTrue(CrossfitPolicy.eligible(row,date(2025,12,31),(group+1)%5))
        self.assertFalse(CrossfitPolicy.eligible(row,date(2025,12,31),group))
        self.assertFalse(CrossfitPolicy.eligible({**row,'as_of':'2025-11-25'},date(2025,12,31),(group+1)%5))
        self.assertFalse(CrossfitPolicy.eligible({**row,'company':self.company(True)},date(2025,12,31),(group+1)%5))
        self.assertFalse(CrossfitPolicy.eligible({**row,'opening':-1},date(2025,12,31),(group+1)%5))

    def test_company_weights_do_not_count_repeated_windows_as_extra_companies(self):
        rows=[{'company':'a'}]*4+[{'company':'b'}]
        weights=CrossfitPolicy.weights(rows)
        self.assertEqual(weights.mean(),1.)
        self.assertEqual(weights[:4].sum(),weights[4])

    def rows(self):
        base={'company':self.company(),'phase':'validation','cutoff':'2026-01-31','current':.6,'risk18':False}
        return [{**base,'label':True,'risk21':True,'crossfit_score':.06} for _ in range(5)]+[
            {**base,'label':False,'risk21':True,'crossfit_score':.03}]

    def test_early_selector_reduces_false_positives_without_losing_tp(self):
        choice=CrossfitPolicy.choose(self.rows())['selected']
        self.assertEqual(choice['threshold'],.05)
        self.assertEqual(choice['metrics']['tp'],5)
        self.assertEqual(choice['metrics']['fp'],0)

    def test_no_signal_and_low_support_keep_existing_policy(self):
        rows=self.rows()
        for row in rows:row['crossfit_score']=.01
        self.assertIsNone(CrossfitPolicy.choose(rows)['selected']['threshold'])
        self.assertIsNone(CrossfitPolicy.choose(self.rows()[:4])['selected']['threshold'])

    def test_late_and_heldout_rows_cannot_choose_threshold(self):
        for change in ({'company':self.company(True)},{'cutoff':'2026-07-31'},{'phase':'late_development'}):
            with self.assertRaises(ValueError):CrossfitPolicy.choose([{**r,**change} for r in self.rows()])

    def test_future_rows_do_not_change_eligible_training(self):
        company=self.company(); group=(CrossfitPolicy.group(company)+1)%5
        past={'company':company,'opening':0,'as_of':'2025-01-01'}
        future={**past,'as_of':'2030-01-01','features':np.full(34,999).tolist()}
        select=lambda rows:[r for r in rows if CrossfitPolicy.eligible(r,date(2025,12,31),group)]
        self.assertEqual(select([past]),select([past,future]))

    def test_paired_bootstrap_resamples_whole_company(self):
        base={'risk18':False,'current':.5,'risk21':False}
        rows=[{**base,'company':'a','label':True,'crossfit_score':.1}]*3+[
            {**base,'company':'b','label':False,'crossfit_score':0.,'risk21':True}]
        result=CrossfitExperiment.cluster_bootstrap(rows,.05)
        self.assertEqual(result['differences']['tp']['point'],3.)
        self.assertEqual(result['differences']['tp']['ci95'],[0.,6.])
        self.assertEqual(result['differences']['fp']['point'],-1.)
        self.assertLess(result['differences']['recall']['defined_resamples'],1000)


if __name__=='__main__':unittest.main()
