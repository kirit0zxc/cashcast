"""Признаки используют прогнозы, не будущие факты; единицы неизменны."""
from copy import deepcopy
import unittest
import numpy as np
from .forecast_features import ForecastFeatures


class ForecastFeatureTests(unittest.TestCase):
    @staticmethod
    def row():
        return {'scale':10.,'opening_minor':100,'base_features':np.array([1.,2.]),
                'current_interval':np.tile([90.,100.,110.],(30,1)),
                'current':.2,'fallback':False,'truth':np.zeros((30,3))}

    def test_future_truth_does_not_enter_features(self):
        row=self.row();changed=deepcopy(row);changed['truth'][:]=10**10
        np.testing.assert_array_equal(ForecastFeatures.extend(row,row['current_interval']),
                                      ForecastFeatures.extend(changed,row['current_interval']))

    def test_scale_and_translation_invariance(self):
        row=self.row();changed=deepcopy(row)
        changed['scale']*=5;changed['opening_minor']=row['opening_minor']*5+700
        changed['current_interval']=row['current_interval']*5+700
        np.testing.assert_array_equal(ForecastFeatures.extend(row,row['current_interval']),
                                      ForecastFeatures.extend(changed,changed['current_interval']))

    def test_shapes_nan_and_probability_missing(self):
        row=self.row()
        with self.assertRaises(ValueError):ForecastFeatures.extend(row,np.zeros((29,3)))
        with self.assertRaises(ValueError):ForecastFeatures.extend(row,np.full((30,3),np.nan))
        row['current']=None;row['fallback']=True
        values=ForecastFeatures.extend(row,row['current_interval'])
        np.testing.assert_array_equal(values[-3:],[0,1,1])
        self.assertEqual(len(values),41)


if __name__=='__main__':unittest.main()
