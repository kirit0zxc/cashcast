"""Новые срезы не захватывают будущие целевые периоды."""
from datetime import date,timedelta
import unittest
from .weekly_reserve import WeeklyReserve


class WeeklyTests(unittest.TestCase):
    def test_complete_targets_stay_in_training_period(self):
        dates=WeeklyReserve.dates()
        self.assertEqual(dates[0],date(2024,12,31))
        self.assertTrue(all(b-a==timedelta(days=7) for a,b in zip(dates,dates[1:])))
        self.assertTrue(all(d+timedelta(days=30)<=date(2025,12,31) for d in dates))
        self.assertGreater(dates[-1]+timedelta(days=37),date(2025,12,31))


if __name__=='__main__':unittest.main()
