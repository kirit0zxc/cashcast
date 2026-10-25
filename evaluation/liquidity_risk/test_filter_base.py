"""Границы фильтра и тождество с предыдущим кандидатом при нулевом пороге."""
import unittest

from .filter_base import FilterBase


class FilterTests(unittest.TestCase):
    def test_zero_preserves_previous_rule(self):
        for base in (False,True):
            for score in (0.,.001,.024,.025,.5):
                row={'risk18':base,'scores':{'rolling_all':score}}
                self.assertEqual(FilterBase.flags([row],0.),[base or score>=.025])

    def test_confirm_boundary_and_extra_alert(self):
        rows=[{'risk18':True,'scores':{'rolling_all':.005}},
              {'risk18':True,'scores':{'rolling_all':.004}},
              {'risk18':False,'scores':{'rolling_all':.025}}]
        self.assertEqual(FilterBase.flags(rows,.005),[True,False,True])

    def test_reject_unknown_gate(self):
        with self.assertRaises(ValueError):FilterBase.flags([],.4)


if __name__=='__main__':unittest.main()
