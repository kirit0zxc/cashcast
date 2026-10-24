"""Проверки денежной сверки и честного выбора компонентов ансамбля."""
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import numpy as np

from evaluation.fallback_model import test_model as fixtures
from app.modules.contracts import Direction, TxnDTO
from .specialists import SpecialistMath, SpecialistPolicy


class SpecialistTests(unittest.TestCase):
    def test_reconciliation_exact_and_nonnegative(self):
        rng = np.random.default_rng(18)
        for _ in range(100):
            flows = rng.integers(0, 100000, (30,2))
            balance = rng.integers(-100000,100000,30)
            result = SpecialistMath.reconcile(flows,balance,5000)
            np.testing.assert_array_equal(5000+np.cumsum(result[:,0]-result[:,1]), balance)
            self.assertTrue(np.all(result[:,:2]>=0))

    def test_already_consistent_flows_unchanged(self):
        flows = np.array([[2,10],[20,3],[0,0]])
        balance = 5+np.cumsum(flows[:,0]-flows[:,1])
        np.testing.assert_array_equal(SpecialistMath.reconcile(flows,balance,5)[:,:2],flows)

    def test_reconciliation_is_minimum_integer_l2(self):
        for incoming in range(5):
            for outgoing in range(5):
                for delta in range(-4,5):
                    result = SpecialistMath.reconcile([[incoming,outgoing]],[delta],0)
                    actual = (result[0,0]-incoming)**2+(result[0,1]-outgoing)**2
                    costs = [(i-incoming)**2+(i-delta-outgoing)**2 for i in range(12) if i-delta>=0]
                    self.assertEqual(actual,min(costs))

    def test_bad_sums_rejected(self):
        for flows, balance in (([[1,2]],[np.nan]), ([[1e40,0]],[0]), ([[1,2],[2,3]],[1])):
            with self.assertRaises(ValueError): SpecialistMath.reconcile(flows,balance,0)

    def test_context_future_and_other_accounts_ignored(self):
        data = fixtures.ModelTests.example()
        polluted = replace(data,txns=data.txns+[
            TxnDTO("future",data.account_id,data.as_of+timedelta(days=1),10**9,Direction.OUT),
            TxnDTO("other","other",data.as_of,10**9,Direction.OUT)])
        left,right=SpecialistMath.contexts(data),SpecialistMath.contexts(polluted)
        for name in left:
            np.testing.assert_array_equal(left[name][0],right[name][0])
            self.assertEqual(left[name][1],right[name][1])

    def test_context_shapes_and_no_negative_past_flow(self):
        values = SpecialistMath.contexts(fixtures.ModelTests.example())
        self.assertLessEqual(values["balance84"][0].shape[1],84)
        self.assertEqual(values["flow365"][0].shape[0],2)
        self.assertTrue(np.all(values["flow365"][0]>=0))
        self.assertEqual(values["balance365"][0][0,-1],0)

    def test_rank_ties_and_single_class(self):
        tied=SpecialistMath.rank_metrics([0,1],[3,3])
        self.assertEqual(tied["roc_auc"],.5)
        self.assertEqual(tied["average_precision"],.5)
        self.assertIsNone(tied["probability"])
        self.assertNotIn("brier",tied)
        self.assertIsNone(SpecialistMath.rank_metrics([0,0],[1,2])["roc_auc"])
        self.assertIsNone(SpecialistMath.rank_metrics([],[])["average_precision"])
        self.assertEqual(SpecialistMath.rank_metrics([0,1],[-2,2])["roc_auc"],1)

    @staticmethod
    def risk_rows():
        rows=[]
        for index in range(20):
            positive=index<5
            truth=np.zeros((30,3));truth[:,2]=-1 if positive else 10
            interval=np.full((30,3),-1 if positive or index==5 else 10)
            rows.append({"opening":10,"company":str(index),"truth":truth,
                         "probability":.9 if positive or index<10 else .1,
                         "intervals":{"balance84":interval,"balance365":interval},"fallback":False})
        return rows

    def test_risk_policy_preserves_early_recall_and_limits_fp(self):
        result=SpecialistPolicy.choose_risk(self.risk_rows())
        selected=result["trials"][result["selected"]]
        self.assertEqual(selected["recall"],1)
        self.assertLess(selected["fp"],result["trials"]["current"]["fp"])

    def test_too_few_positives_keeps_current(self):
        self.assertEqual(SpecialistPolicy.choose_risk(self.risk_rows()[3:])["selected"],"current")

    def test_missing_risk_not_counted_as_zero(self):
        rows=self.risk_rows();rows[0]["probability"]=None
        self.assertEqual(SpecialistPolicy.risk(rows,"current")["n"],19)
        with self.assertRaises(ValueError): SpecialistPolicy.risk(rows,"current",7)

    def test_fallback_uses_current_alert(self):
        rows=self.risk_rows()
        for r in rows: r["fallback"]=True
        self.assertEqual(SpecialistPolicy.risk(rows,"current"),SpecialistPolicy.risk(rows,"balance365"))

    def test_assembly_does_not_replace_original_models(self):
        row={"opening":0,"models":{"current":np.tile([10,8,5],(30,1))}}
        before=deepcopy(row["models"])
        SpecialistPolicy.assemble([row],{"balance":"current","inflow":"current","outflow":"current"})
        np.testing.assert_array_equal(before["current"],row["models"]["current"])
        np.testing.assert_array_equal(np.cumsum(row["models"]["specialists_reconciled"][:,0]-row["models"]["specialists_reconciled"][:,1]),np.full(30,5))

    def test_component_selection_uses_given_early_rows_only(self):
        truth=np.tile([10,5,100],(30,1))
        models={n:truth+np.array([2,2,10]) for n in set(SpecialistPolicy.BALANCES+SpecialistPolicy.FLOWS)}
        models["balance365"]=truth.copy()
        models["direct"]=truth+np.array([0,2,5])
        models["flow365"]=truth+np.array([2,0,20])
        row={"truth":truth,"models":models,"company":"sample","cutoff":"2026-01-31","cohort":"established","opening":100}
        result=SpecialistPolicy.choose([row])
        self.assertEqual((result["balance"],result["inflow"],result["outflow"]),("balance365","direct","flow365"))
        with self.assertRaises(ValueError): SpecialistPolicy.choose([])


if __name__=="__main__": unittest.main()
