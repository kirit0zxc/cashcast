"""Проверки политики, медианного netflow и подготовки внешней модели."""
import sys
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"backend"))
from app.modules.contracts import Direction,TxnDTO
from evaluation.fallback_model import test_model as fixtures
from .chronos_trial import BalanceContext
from .net_quantiles import NetCandidate
from .policy import RecallPolicy


class ExtensionTests(unittest.TestCase):
    def test_context_ends_at_known_opening(self):
        data=fixtures.ModelTests.example()
        values,scale=BalanceContext.make(data)
        self.assertEqual(values[-1],0)
        self.assertGreater(scale,0)

    def test_context_future_cannot_leak(self):
        data=fixtures.ModelTests.example()
        future=TxnDTO("future",data.account_id,data.as_of+timedelta(days=1),10**9,Direction.OUT)
        original=BalanceContext.make(data)
        changed=BalanceContext.make(replace(data,txns=data.txns+[future]))
        np.testing.assert_array_equal(original[0],changed[0])
        self.assertEqual(original[1],changed[1])

    def test_context_does_not_bridge_last_reconciliation_break(self):
        data=fixtures.ModelTests.example()
        broken=replace(data,daily_balances=data.daily_balances[:-1]+[replace(data.daily_balances[-1],closing_balance_minor=data.opening_balance_minor+500)])
        self.assertIsNone(BalanceContext.make(broken))

    @staticmethod
    def examples():
        return [{"company":str(i),"label":int(i<5),"opening":1,
                 "scores":{"current":.9 if i<5 else .6,"reserve4":.8 if i<5 else .05}} for i in range(30)]

    def test_policy_hard_recall_preserves_baseline(self):
        choice=RecallPolicy.choose(self.examples())
        self.assertTrue(choice["feasible"])
        self.assertGreaterEqual(choice["selected"]["recall"],choice["baseline"]["recall"])
        self.assertLessEqual(choice["selected"]["fpr"],.2)

    def test_policy_does_not_mutate_inputs(self):
        rows=self.examples();before=deepcopy(rows)
        RecallPolicy.choose(rows)
        self.assertEqual(rows,before)

    def test_no_positives_cannot_validate_recall(self):
        rows=self.examples()[5:]
        self.assertFalse(RecallPolicy.choose(rows)["feasible"])

    def test_unavailable_is_not_zero_score(self):
        rows=self.examples()
        rows[0]["scores"]["current"]=None
        self.assertEqual(len(RecallPolicy.eligible(rows)),29)

    def test_net_overflow_rejected_before_integer_cast(self):
        class Fake:
            def predict(self,x):
                return np.ones((len(x),3))*1e40
        candidate=NetCandidate(4,None);candidate.model=Fake()
        with self.assertRaises(ValueError):
            candidate.predict(fixtures.ModelTests.example())


if __name__=="__main__":
    unittest.main()
