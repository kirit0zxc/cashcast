"""Причинность длинной истории и неизменный селектор29 под новым именем."""
from datetime import date,timedelta
import unittest
import numpy as np
from .long_history_risk import LongHistoryFeatures,LongPolicy
from app.modules.contracts import Direction,TxnDTO
from . import test_diverse_risk as fixtures


class LongHistoryTests(unittest.TestCase):
    def test_future_and_foreign_do_not_change_features(self):
        day=date(2026,1,31)
        txns=[TxnDTO('a','a',day-timedelta(days=40),100000,Direction.IN),TxnDTO('b','a',day,20000,Direction.OUT)]
        original=LongHistoryFeatures.make('a',day,txns)
        additions=[TxnDTO('future','a',day+timedelta(days=1),10**12,Direction.OUT),
                   TxnDTO('foreign','other',day,10**12,Direction.IN)]
        np.testing.assert_array_equal(original,LongHistoryFeatures.make('a',day,txns+additions))

    def test_ancient_amounts_ignored_and_initial_zero_in_drawdown(self):
        day=date(2026,1,31)
        old=TxnDTO('old','a',day-timedelta(days=500),123,Direction.IN)
        now=TxnDTO('now','a',day,10000,Direction.OUT)
        values=LongHistoryFeatures.make('a',day,[old,now])
        huge=TxnDTO('old','a',old.booked_on,10**14,Direction.IN)
        np.testing.assert_array_equal(values,LongHistoryFeatures.make('a',day,[huge,now]))
        self.assertEqual(values.shape,(52,));self.assertEqual(values[8],1.)

    def test_short_history_coverage_and_no_past(self):
        day=date(2026,1,31)
        row=TxnDTO('now','a',day,10000,Direction.OUT)
        self.assertEqual(LongHistoryFeatures.make('a',day,[row])[0],1/28)
        with self.assertRaises(ValueError):LongHistoryFeatures.make('a',day,[])

    def test_selector_maps_model_without_changing_threshold(self):
        rows=[{**r,'extended_score':r['cat_score']} for r in fixtures.DiverseTests().rows()]
        choice=LongPolicy.choose(rows)['selected']
        self.assertEqual((choice['mode'],choice['threshold']),('extended',.025))
        self.assertEqual(sum(LongPolicy.flags(rows,choice)),5)


if __name__=='__main__':unittest.main()
