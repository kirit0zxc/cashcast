"""Согласованность групп runtime и обучения, безопасный недоступный риск."""
from datetime import date
import unittest

from evaluation.fallback_model.data import Dataset
from .company_crossfit import CrossfitPolicy
from .crossfit_runtime import CrossfitAddon


class CrossfitRuntimeTests(unittest.TestCase):
    def test_runtime_group_assignment_matches_training(self):
        for i in range(1000):
            company='synthetic'+str(i)
            self.assertEqual(CrossfitAddon.groups(company),list(range(5)) if Dataset.heldout(company) else [CrossfitPolicy.group(company)])

    def test_checkpoint_is_never_selected_from_future(self):
        models={'2026-01-31':[], '2026-03-31':[]}
        self.assertIsNone(CrossfitAddon.select_model(models,date(2026,1,1)))
        self.assertEqual(CrossfitAddon.select_model(models,date(2026,3,1)),'2026-01-31')

    def test_unavailable_base_is_not_promoted_and_is_not_mutated(self):
        base={'candidate':'cashcast-research-18','status':'unavailable'}
        actual=CrossfitAddon.apply(base,{},None,None)
        self.assertEqual(actual['risk_extension']['status'],'unavailable')
        self.assertNotIn('risk_extension',base)


if __name__=='__main__':unittest.main()
