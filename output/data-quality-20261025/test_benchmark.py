"""Причинность и сохранность данных при маскировании истории."""
from datetime import date,timedelta
from types import SimpleNamespace
import unittest
import numpy as np
import benchmark as b
from evaluation.model_compare.organizers import Window

class MaskTests(unittest.TestCase):
    def window(self):
        return Window('test',date(2026,1,10),'test',100.,84,np.ones(84),np.ones(84),np.ones(84)*100,np.zeros(30),np.zeros(30),0,np.ones((30,3)))

    def test_future_discrepancy_cannot_change_history(self):
        w=self.window()
        c=b.cleaned(w,[(date(2026,1,9),date(2026,1,11))])
        np.testing.assert_equal(w.inc,c.inc)

    def test_mask_only_uncertain_span_and_preserve_truth_balance(self):
        w=self.window()
        c=b.cleaned(w,[(date(2026,1,7),date(2026,1,10))])
        self.assertTrue(np.isnan(c.inc[-3:]).all())
        self.assertTrue(np.isfinite(c.inc[:-3]).all())
        self.assertTrue(np.isnan(c.bal[-3:-1]).all())
        self.assertEqual(c.bal[-1],100)
        np.testing.assert_equal(w.truth,c.truth)
        self.assertTrue(np.isfinite(w.inc).all())

    def test_non_overlapping_old_break_does_not_mask(self):
        w=self.window()
        np.testing.assert_equal(b.cleaned(w,[(date(2024,1,1),date(2024,1,2))]).inc,w.inc)

    def test_perfect_prediction_metrics(self):
        y=np.array([[100.,-100.]])
        m=b.metrics(y,y,np.array([100.]))
        self.assertEqual(m['mae_rub'],0)
        self.assertEqual(m['new_gap']['tp'],1)
        self.assertEqual(m['daily_negative']['tp'],1)

if __name__=='__main__': unittest.main()
