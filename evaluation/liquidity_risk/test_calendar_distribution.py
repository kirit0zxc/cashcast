"""Причинность календаря и абляция исторического денежного остатка."""
import unittest
from dataclasses import replace
from datetime import timedelta

import numpy as np

from evaluation.fallback_model import test_model as fixtures
from .calendar_distribution import FlowExperiment,CalendarFeatures
from app.modules.contracts import TxnDTO,Direction


class CalendarTests(unittest.TestCase):
    def test_calendar_future_ignored(self):
        data=fixtures.ModelTests.example()
        later=replace(data,txns=data.txns+[TxnDTO('future',data.account_id,data.as_of+timedelta(days=1),10**10,Direction.OUT)])
        np.testing.assert_array_equal(CalendarFeatures.make(data,100),CalendarFeatures.make(later,100))

    def test_calendar_finite_for_short_history(self):
        data=fixtures.ModelTests.example()
        data=replace(data,txns=data.txns[-3:],daily_balances=data.daily_balances[-3:])
        self.assertTrue(np.isfinite(CalendarFeatures.make(data,100)).all())

    def test_flow_features_ignore_coherent_balance_translation(self):
        data=fixtures.ModelTests.example()
        shifted=replace(data,opening_balance_minor=data.opening_balance_minor+1000000,
                        daily_balances=[replace(b,closing_balance_minor=b.closing_balance_minor+1000000) for b in data.daily_balances])
        for variant in ('flow_only','calendar'):
            runner=object.__new__(FlowExperiment);runner.variant=variant
            left=runner.make(data,np.zeros((30,3)))
            right=runner.make(shifted,np.zeros((30,3)))
            np.testing.assert_array_equal(left['features'],right['features'])
            self.assertNotEqual(left['opening'],right['opening'])


if __name__=='__main__':unittest.main()
