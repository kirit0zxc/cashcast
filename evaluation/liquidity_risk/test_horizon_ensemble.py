"""Веса смеси, воспроизводимость фиксированного baseline и отсутствие мутаций."""
import unittest
import numpy as np
from .horizon_ensemble import HorizonWeights


class HorizonTests(unittest.TestCase):
    def test_weights_are_convex_and_continuous(self):
        weights=HorizonWeights.weights(.25,[.25,.75,1.])
        np.testing.assert_allclose(weights.sum(axis=1),1.)
        self.assertTrue(np.all((weights>=0)&(weights<=1)))
        self.assertLessEqual(float(abs(np.diff(weights[:,2])).max()),.75*.5/7+1e-12)

    def test_reproduces_fixed75_25(self):
        base=np.random.default_rng(12).integers(-10**7,10**7,(4,30,3))
        expected=np.rint(.25*base[:,:,1]+.75*base[:,:,2]).astype(np.int64)
        np.testing.assert_array_equal(HorizonWeights.predict(base,0.,[.75]*3),expected)

    def test_inputs_unchanged_and_money_integer(self):
        base=np.ones((2,30,3));before=base.copy()
        result=HorizonWeights.predict(base,.25,[0,.5,1])
        np.testing.assert_array_equal(base,before)
        self.assertEqual(result.dtype,np.dtype('int64'))

    def test_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):HorizonWeights.weights(-1,[0,0,0])
        with self.assertRaises(ValueError):HorizonWeights.predict(np.full((1,30,3),np.nan),0,[0,0,0])


if __name__=='__main__':unittest.main()
