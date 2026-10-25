"""Защита временных границ обучения и независимого разделения компаний."""
from datetime import date,timedelta
import unittest

from evaluation.fallback_model.data import Dataset
from .rolling_peer_risk import RollingPolicy


class RollingTests(unittest.TestCase):
    @staticmethod
    def row(company=None,as_of='2025-11-24',opening=100):
        if company is None:company=next(f'C{i:03d}' for i in range(1,151) if not Dataset.heldout(f'C{i:03d}'))
        return {'company':company,'as_of':as_of,'opening':opening}

    def test_confirmation_must_finish_before_training_cutoff(self):
        row=self.row(as_of='2026-01-01');boundary=date(2026,1,1)+timedelta(days=37)
        self.assertFalse(RollingPolicy.eligible(row,boundary-timedelta(days=1),'rolling_all'))
        self.assertTrue(RollingPolicy.eligible(row,boundary,'rolling_all'))

    def test_static_never_learns_from_2026(self):
        row=self.row(as_of='2026-01-01')
        self.assertFalse(RollingPolicy.eligible(row,date(2026,8,31),'static_all'))
        self.assertTrue(RollingPolicy.eligible(row,date(2026,8,31),'rolling_all'))

    def test_heldout_company_is_always_excluded(self):
        name=next(f'C{i:03d}' for i in range(1,151) if Dataset.heldout(f'C{i:03d}'))
        for mode in RollingPolicy.MODES:
            self.assertFalse(RollingPolicy.eligible(self.row(company=name),date(2026,8,31),mode))

    def test_new_gap_specialist_does_not_train_on_negative_opening(self):
        self.assertFalse(RollingPolicy.eligible(self.row(opening=-1),date(2026,8,31),'rolling_new'))
        self.assertTrue(RollingPolicy.eligible(self.row(opening=0),date(2026,8,31),'rolling_new'))

    def test_selection_rejects_late_periods(self):
        with self.assertRaises(ValueError):RollingPolicy.choose([{'cutoff':'2026-07-31'}])


if __name__=='__main__':unittest.main()
