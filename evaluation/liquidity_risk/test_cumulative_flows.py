"""Причинное накопление, монотонность и сверка денег после проекции."""
import unittest

import numpy as np

from .cumulative_flows import CumulativeMath,CumulativePolicy
from .flow_evaluate import FlowEvaluation,FlowPolicy


class CumulativeTests(unittest.TestCase):
    def test_appending_future_does_not_change_context_prefix(self):
        past=np.array([[1.,2.,0.],[0.,3.,4.]])
        full=np.column_stack([past,[[999.],[888.]]])
        np.testing.assert_array_equal(CumulativeMath.context(past,100),CumulativeMath.context(full,100)[:,:3])

    def test_projection_preserves_exact_money_identity(self):
        median=np.array([[2.,1.,3.]+[3.]*27,[1.,2.,1.]+[4.]*27])
        values=np.repeat(median[:,:,None],3,axis=2)
        result=CumulativeMath.project(values,np.array([1.,1.]),123)
        self.assertTrue(np.all(result[:,:2]>=0))
        np.testing.assert_array_equal(123+np.cumsum(result[:,0]-result[:,1]),result[:,2])
        self.assertEqual(result[:,0].sum(),2_000_000)
        self.assertEqual(result[:,1].sum(),3_000_000)

    def test_absolute_offset_does_not_change_future_cash(self):
        values=np.ones((2,30,3))*3
        first=CumulativeMath.project(values,[1.,1.],123)
        second=CumulativeMath.project(values+8,[9.,9.],123)
        np.testing.assert_array_equal(first,second)

    def test_invalid_flows_or_quantiles_are_rejected(self):
        with self.assertRaises(ValueError):CumulativeMath.context([[1.,-2.],[0.,0.]],100)
        with self.assertRaises(ValueError):CumulativeMath.project(np.full((2,30,3),np.nan),[0.,0.],0)

    def test_existing_flow_policy_remains_default(self):
        self.assertIs(FlowEvaluation.POLICY,FlowPolicy)
        self.assertEqual(len(CumulativePolicy.NAMES),7)
        row={'models':{'current':np.ones((30,3))},'fallback':True}
        np.testing.assert_array_equal(CumulativePolicy.assemble(row,'cum_ft300','cum_ft100'),row['models']['current'])


if __name__=='__main__':unittest.main()
