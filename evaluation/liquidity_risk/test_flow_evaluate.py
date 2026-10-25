"""Нативныйbaseline не пересчитывается, новые пары обязаны точно сверять деньги."""
import unittest
import numpy as np
from .flow_evaluate import FlowPolicy


class FlowPolicyTests(unittest.TestCase):
    @staticmethod
    def rows():
        truth=np.column_stack([np.full(30,10),np.full(30,5),100+5*np.arange(1,31)])
        base=truth+np.array([1,1,10])
        row={'company':'a','cutoff':'2026-01-31','cohort':'established','opening':100,'truth':truth,
             'models':{n:base.copy() for n in FlowPolicy.NAMES}}
        row['models']['flow_ft100']=truth.copy()
        return [row]

    def test_baseline_is_unchanged_and_pairs_reconcile(self):
        row=self.rows()[0]
        np.testing.assert_array_equal(FlowPolicy.assemble(row,'keep_current',None),row['models']['current'])
        coherent=FlowPolicy.assemble(row,'current','current')
        np.testing.assert_array_equal(100+np.cumsum(coherent[:,0]-coherent[:,1]),coherent[:,2])
        self.assertFalse(np.array_equal(coherent,row['models']['current']))

    def test_selects_better_pair_without_future_policy_changes(self):
        choice=FlowPolicy.choose(self.rows())['selected']
        self.assertEqual((choice['incoming'],choice['outgoing']),('flow_ft100','flow_ft100'))
        self.assertTrue(choice['eligible'])

    def test_perfect_baseline_wins_ties(self):
        rows=self.rows()
        for n in FlowPolicy.NAMES:rows[0]['models'][n]=rows[0]['truth'].copy()
        self.assertEqual(FlowPolicy.choose(rows)['selected']['incoming'],'keep_current')

    def test_bad_flows_rejected(self):
        row=self.rows()[0];row['models']['flow_ft100'][0,0]=-1
        with self.assertRaises(ValueError):FlowPolicy.assemble(row,'flow_ft100','flow_ft100')

    def test_missing_context_preserves_native_current(self):
        row=self.rows()[0];row['fallback']=True
        np.testing.assert_array_equal(FlowPolicy.assemble(row,'flow_ft100','flow_ft100'),row['models']['current'])


if __name__=='__main__':unittest.main()
