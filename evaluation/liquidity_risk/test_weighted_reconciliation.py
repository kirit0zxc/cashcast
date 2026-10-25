"""Математика взвешенного согласования и причинность дисперсий."""
from dataclasses import replace
from datetime import date,timedelta
import unittest

import numpy as np

from evaluation.fallback_model import test_model as fixtures
from evaluation.fallback_model.data import Dataset
from app.modules.contracts import Direction,TxnDTO
from .specialists import SpecialistMath
from .weighted_reconciliation import WeightedReconciliation


class WeightedTests(unittest.TestCase):
    def test_equal_variance_matches_existing_integer_l2(self):
        rng=np.random.default_rng(27)
        for _ in range(30):
            flows=rng.integers(0,1000,(30,2));balance=rng.integers(-1000,1000,30)
            actual=WeightedReconciliation.project(flows,balance,123,np.ones((30,2)))
            np.testing.assert_array_equal(actual,SpecialistMath.reconcile(flows,balance,123))

    def test_more_variable_channel_absorbs_more_correction(self):
        flows=np.full((30,2),1000);balance=np.arange(1,31)*100
        actual=WeightedReconciliation.project(flows,balance,0,np.tile([9.,1.],(30,1)))
        np.testing.assert_array_equal(actual[:,:2],np.tile([1090,990],(30,1)))
        np.testing.assert_array_equal(np.cumsum(actual[:,0]-actual[:,1]),balance)

    def test_nonnegative_boundary_and_baseline_not_mutated(self):
        flows=np.zeros((30,2),dtype=int);original=flows.copy();balance=np.arange(1,31)*-100
        actual=WeightedReconciliation.project(flows,balance,0,np.tile([100.,1.],(30,1)))
        self.assertTrue((actual[:,:2]>=0).all())
        np.testing.assert_array_equal(flows,original)
        np.testing.assert_array_equal(np.cumsum(actual[:,0]-actual[:,1]),balance)

    def test_variance_floor_and_older_history_ignored(self):
        past=np.zeros((2,84));first=WeightedReconciliation.variances(past,100,date(2026,1,31))
        np.testing.assert_array_equal(first,np.full((30,2),10000.))
        longer=np.column_stack([np.full((2,100),999),past])
        np.testing.assert_array_equal(first,WeightedReconciliation.variances(longer,100,date(2026,1,31)))

    def test_future_and_foreign_transactions_do_not_change_weights(self):
        data=fixtures.ModelTests.example()
        polluted=replace(data,txns=data.txns+[
            TxnDTO('future27',data.account_id,data.as_of+timedelta(days=1),10**9,Direction.OUT),
            TxnDTO('foreign27','other',data.as_of,10**9,Direction.OUT)])
        left=SpecialistMath.contexts(data)['flow365'];right=SpecialistMath.contexts(polluted)['flow365']
        np.testing.assert_array_equal(WeightedReconciliation.variances(*left,data.as_of),WeightedReconciliation.variances(*right,data.as_of))

    def test_perfect_current_is_kept_and_late_selection_rejected(self):
        company=next('test'+str(i) for i in range(100) if not Dataset.heldout('test'+str(i)))
        truth=np.ones((30,3),dtype=int)
        row={'company':company,'cutoff':'2026-01-31','truth':truth,'models':{m:truth.copy() for m in ('current','equal','weighted')}}
        self.assertEqual(WeightedReconciliation.choose([row])['selected'],'keep_current')
        with self.assertRaises(ValueError):WeightedReconciliation.choose([{**row,'cutoff':'2026-07-31'}])

    def test_invalid_or_short_history_rejected(self):
        with self.assertRaises(ValueError):WeightedReconciliation.variances(np.ones((2,27)),1,date(2026,1,31))
        with self.assertRaises(ValueError):WeightedReconciliation.variances(np.full((2,84),np.nan),1,date(2026,1,31))


if __name__=='__main__':unittest.main()
