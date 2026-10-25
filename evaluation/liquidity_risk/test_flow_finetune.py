"""Ряды потоков начинаются после подтверждённого остатка и не пересекают несверки."""
from datetime import date,timedelta
from types import SimpleNamespace
import unittest
import numpy as np
from .flow_finetune import FlowTrainingSegments
from evaluation.fallback_model.data import Dataset


class FlowSegmentTests(unittest.TestCase):
    @staticmethod
    def data(days=100):
        start=date(2025,1,1)
        txns=[SimpleNamespace(account_id='a',booked_on=start+timedelta(days=i),amount_minor=10,direction='in') for i in range(days+1)]
        balances={start:100,start+timedelta(days=days):100+days*10}
        return SimpleNamespace(transactions={'a':txns},balances={'a':balances})

    def test_first_day_is_anchor_not_unverified_flow(self):
        inputs,manifest=FlowTrainingSegments.build(self.data())
        self.assertEqual(inputs[0].shape,(2,100))
        self.assertEqual(manifest[0]['start'],'2025-01-02')
        np.testing.assert_allclose(inputs[0][0],.00001)
        np.testing.assert_array_equal(inputs[0][1],0)

    def test_future_and_foreign_ignored(self):
        data=self.data();before=FlowTrainingSegments.build(data)[0][0]
        data.transactions['a'].extend([
            SimpleNamespace(account_id='a',booked_on=date(2026,1,1),amount_minor=10**10,direction='out'),
            SimpleNamespace(account_id='other',booked_on=date(2025,2,1),amount_minor=10**10,direction='out')])
        data.balances['a'][date(2026,1,1)]=-10**10
        np.testing.assert_array_equal(before,FlowTrainingSegments.build(data)[0][0])

    def test_too_short_or_unreconciled_rejected(self):
        with self.assertRaises(ValueError):FlowTrainingSegments.build(self.data(85))
        data=self.data();last=max(data.balances['a']);data.balances['a'][last]+=1
        with self.assertRaises(ValueError):FlowTrainingSegments.build(data)

    def test_heldout_excluded(self):
        data=self.data();name=next(str(i) for i in range(50) if Dataset.heldout(str(i)))
        data.transactions[name]=[];data.balances[name]=data.balances['a']
        self.assertEqual(len(FlowTrainingSegments.build(data)[0]),1)


if __name__=='__main__':unittest.main()
