"""Денежные MSE-веса и фиксированная смесь не подстраиваются под контроль."""
import unittest
import numpy as np
from .block_mean_median import money_mse_weights,MeanMedian


class MeanMedianTests(unittest.TestCase):
    def test_squared_money_scale_and_equal_company_window_count(self):
        rows=[{'company':'a','scale':2.}]*2+[{'company':'b','scale':1.}]
        weights=money_mse_weights(rows)
        self.assertAlmostEqual(weights.mean(),1.)
        np.testing.assert_allclose(weights[:3],weights[3:6])
        np.testing.assert_allclose(weights[:3]/weights[6:],[2.,2.,2.])
        self.assertAlmostEqual(weights[2]/weights[0],(16/7)**2)

    def test_fixed_half_mean_cannot_fit_weights(self):
        class Model:
            def __init__(self,value):self.value=value
            def predict(self,x,**kwargs):return np.ones(len(x))*self.value
        np.testing.assert_array_equal(MeanMedian(Model(2),Model(10)).predict(np.zeros((3,2))),[6,6,6])


if __name__=='__main__':unittest.main()
