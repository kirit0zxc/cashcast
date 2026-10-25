"""Группы и время для потоков, включая допустимый отрицательный opening."""
from datetime import date
import unittest
import numpy as np
from .rolling_block_flows import RollingBlockMath
from .company_crossfit import CrossfitPolicy
from . import test_block_flows as fixtures


class RollingBlockTests(unittest.TestCase):
    def test_negative_opening_allowed_but_future_group_excluded(self):
        row={**fixtures.BlockTests().row(),'as_of':'2025-11-24','opening':-100}
        group=CrossfitPolicy.group(row['company']);cutoff=date(2025,12,31)
        self.assertTrue(RollingBlockMath.eligible(row,cutoff,(group+1)%5))
        self.assertFalse(RollingBlockMath.eligible(row,cutoff,group))
        self.assertFalse(RollingBlockMath.eligible({**row,'as_of':'2025-11-25'},cutoff,(group+1)%5))

    def test_same_block_targets_and_company_money_weights_as_static(self):
        row=fixtures.BlockTests().row()
        x,y,w=RollingBlockMath.training([row])
        self.assertEqual(x.shape,(3,104));np.testing.assert_array_equal(y,np.ones((3,2)))
        np.testing.assert_allclose(w,np.array([7,7,16])/10)


if __name__=='__main__':unittest.main()
