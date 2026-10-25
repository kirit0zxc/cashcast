"""Причинность, отсутствие утечек идентификаторов и корректность концентрации."""
import unittest
from dataclasses import replace
from datetime import timedelta

import numpy as np

from evaluation.fallback_model import test_model as fixtures
from .semantic_distribution import SemanticFeatures
from app.modules.contracts import TxnDTO,Direction


class SemanticTests(unittest.TestCase):
    def test_unknown_counterparties_are_not_single_large_customer(self):
        hhi,largest,unknown,count=SemanticFeatures.concentration([(None,100),(None,200),('a',100),('b',100)])
        self.assertEqual(hhi,.5);self.assertEqual(largest,.5)
        self.assertEqual(unknown,.6);self.assertEqual(count,2)

    def test_all_missing_finite(self):
        x=SemanticFeatures.make(fixtures.ModelTests.example(),100)
        self.assertTrue(np.isfinite(x).all())
        self.assertGreater(len(x),100)

    def test_future_and_other_account_do_not_change_features(self):
        data=fixtures.ModelTests.example()
        dirty=replace(data,txns=data.txns+[
            TxnDTO('future',data.account_id,data.as_of+timedelta(days=1),10**9,Direction.OUT,purpose='налог'),
            TxnDTO('foreign','other',data.as_of,10**9,Direction.OUT,purpose='зарплата')])
        np.testing.assert_array_equal(SemanticFeatures.make(data,100),SemanticFeatures.make(dirty,100))

    def test_stable_counterparty_renaming_does_not_change_numbers(self):
        data=fixtures.ModelTests.example()
        left=replace(data,txns=[replace(t,counterparty_ref=str(i%3),purpose='оплата за товар') for i,t in enumerate(data.txns)])
        right=replace(left,txns=[replace(t,counterparty_ref='anonymous-'+t.counterparty_ref) for t in left.txns])
        np.testing.assert_array_equal(SemanticFeatures.make(left,100),SemanticFeatures.make(right,100))


if __name__=='__main__':unittest.main()
