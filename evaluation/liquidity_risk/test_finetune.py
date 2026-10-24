"""Сверка истории дообучения и исключение будущего/контрольных компаний."""
from datetime import date
from types import SimpleNamespace
import unittest
import numpy as np

from .finetune import TrainingSegments
from evaluation.fallback_model.data import Dataset


class SegmentTests(unittest.TestCase):
    @staticmethod
    def txn(day, amount, company="a"):
        return SimpleNamespace(account_id=company, booked_on=day, amount_minor=amount, direction="in")

    def test_confirmed_empty_days_are_reconstructed(self):
        first, last = date(2025, 1, 1), date(2025, 1, 4)
        result = TrainingSegments.segments("a", [self.txn(last, 10)], {first: 100, last: 110}, last)
        np.testing.assert_array_equal(result[0][2], [100,100,100,110])

    def test_gap_not_filled(self):
        first, last = date(2025, 1, 1), date(2025, 1, 4)
        result = TrainingSegments.segments("a", [], {first: 100, last: 110}, last)
        self.assertEqual(len(result), 2)
        self.assertEqual([len(s[2]) for s in result], [1,1])

    def test_future_and_foreign_ignored(self):
        first, last, future = date(2025,1,1), date(2025,1,4), date(2026,1,1)
        result = TrainingSegments.segments("a", [self.txn(last,999,"b"), self.txn(future,999)],
                                          {first:100,last:100,future:999}, last)
        np.testing.assert_array_equal(result[0][2], [100]*4)

    def test_split_and_equal_length_choose_earliest(self):
        companies = [str(i) for i in range(30)]
        balances = {date(2025,1,1):100,date(2025,4,1):100,
                    date(2025,7,1):200,date(2025,9,29):200,date(2026,2,1):200}
        data = SimpleNamespace(transactions={c:[] for c in companies}, balances={c:balances for c in companies})
        inputs, manifest = TrainingSegments.build(data)
        self.assertEqual(len(manifest), sum(not Dataset.heldout(c) for c in companies))
        self.assertTrue(all(r["start"]=="2025-01-01" and r["end"]=="2025-04-01" for r in manifest))
        self.assertTrue(all(np.all(row==0) for row in inputs))


if __name__ == "__main__": unittest.main()
