"""Суммы блоков, копейки, fallback и запрет будущих обучающих окон."""
from copy import deepcopy
import unittest
import numpy as np
from evaluation.fallback_model.data import Dataset
from .block_flows import BlockMath


class BlockTests(unittest.TestCase):
    def row(self):
        company=next('test'+str(i) for i in range(100) if not Dataset.heldout('test'+str(i)))
        return dict(company=company,cutoff='2025-11-01',base_features=np.arange(93.),features=np.arange(132.),
                    scale=100.,truth=np.ones((30,3),dtype=np.int64)*100)

    def test_weights_match_block_money_loss(self):
        row=self.row();x,y,w=BlockMath.training([row])
        self.assertEqual(x.shape,(3,104));np.testing.assert_array_equal(y,np.ones((3,2)))
        np.testing.assert_allclose(w,np.array([7,7,16])/10)

    def test_feature_values_do_not_use_truth(self):
        row=self.row();other=deepcopy(row);other['truth'][:]=999999
        np.testing.assert_array_equal(BlockMath.features(row),BlockMath.features(other))

    def test_training_rejects_unconfirmed_future_or_changed_base(self):
        for change in ({'cutoff':'2025-12-01'},{'base_features':np.zeros(93)}):
            with self.assertRaises((ValueError,AssertionError)):BlockMath.training([{**self.row(),**change}])

    def test_largest_remainder_exact_and_zero_profile_uniform(self):
        np.testing.assert_array_equal(BlockMath.allocate(5,[1,1,1]),[2,2,1])
        np.testing.assert_array_equal(BlockMath.allocate(2,[0,0,0]),[1,1,0])
        for total in (0,1,10001,10**12):
            self.assertEqual(int(BlockMath.allocate(total,np.arange(1,17)).sum()),total)

    def test_block_boundaries_and_cash_identity(self):
        current=np.ones((30,3),dtype=np.int64)*100
        row={'fallback':False,'models':{'current':current},'opening':200}
        result=BlockMath.predict(row,np.array([[1.,2.],[3.,4.],[5.,6.]]),100,1.)
        for i,(start,end) in enumerate(BlockMath.BLOCKS):
            np.testing.assert_array_equal(result[start:end,:2].sum(axis=0),np.array([2*i+1,2*i+2])*100*(end-start))
        np.testing.assert_array_equal(result[:,2],200+np.cumsum(result[:,0]-result[:,1]))

    def test_fallback_preserves_native_inconsistency(self):
        current=np.ones((30,3),dtype=np.int64)*100
        row={'fallback':True,'models':{'current':current},'opening':123}
        np.testing.assert_array_equal(BlockMath.predict(row,None,None,.5),current)


if __name__=='__main__':unittest.main()
