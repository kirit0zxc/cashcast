"""Схема прогнозных признаков, единицы коррекции и защита границ обучения."""
import unittest
import numpy as np

from evaluation.fallback_model.data import Dataset
from .chronos_residual import ResidualMath
from .forecast_features import ForecastFeatures


class ResidualTests(unittest.TestCase):
    @staticmethod
    def owner(heldout=False):
        return next('test'+str(i) for i in range(100) if Dataset.heldout('test'+str(i))==heldout)

    def train_row(self):
        days=np.arange(1,31)
        interval=np.repeat((1000+10*days)[:,None],3,axis=1)
        row={'company':self.owner(),'cutoff':'2025-01-31','scale':100.,'opening_minor':1000,
             'current_interval':interval,'current':.1,'fallback':False,'base_features':np.zeros(93),
             'truth':np.column_stack([days*0,days*0,1000+20*days])}
        row['features']=ForecastFeatures.extend(row,interval)
        return row

    def test_registered_endpoint_indexes_and_residual_units(self):
        row=self.train_row()
        np.testing.assert_allclose(row['features'][list(ResidualMath.END_MEDIAN)],np.array([7,14,30])*.1)
        x,y,w=ResidualMath.training([row])
        self.assertEqual(x.shape,(3,133))
        np.testing.assert_allclose(y,.1)
        np.testing.assert_allclose(w/np.array([7,14,30]),np.full(3,3/51))

    def test_targets_do_not_enter_features(self):
        row=self.train_row();first=ResidualMath.features(row)
        row['truth'][:]=999999999
        np.testing.assert_array_equal(first,ResidualMath.features(row))

    def test_training_rejects_future_or_heldout(self):
        for change in ({'cutoff':'2025-12-01'},{'company':self.owner(True)}):
            with self.assertRaises(ValueError):ResidualMath.training([{**self.train_row(),**change}])

    def test_correction_interpolates_in_minor_units_and_preserves_flows(self):
        truth=self.train_row()['truth']
        current=truth.copy();current[:,2]=999
        chrono=truth.copy();chrono[:,2]=1000+10*np.arange(1,31)
        row={'fallback':False,'models':{'current':current.copy(),'balance365':chrono}}
        actual=ResidualMath.correct(row,[.1,.1,.1],100.,1.)
        np.testing.assert_array_equal(actual[:,2],truth[:,2])
        np.testing.assert_array_equal(actual[:,:2],current[:,:2])
        np.testing.assert_array_equal(row['models']['current'],current)

    def test_fallback_needs_no_forecast_and_keeps_native_current(self):
        row={'fallback':True,'models':{'current':np.ones((30,3),dtype=np.int64)}}
        np.testing.assert_array_equal(ResidualMath.correct(row,None,None,.5),row['models']['current'])

    def test_early_selection_and_boundaries(self):
        truth=np.zeros((30,3),dtype=np.int64);base=truth.copy();base[:,2]=100
        row={'company':self.owner(),'cutoff':'2026-01-31','cohort':'established','opening':1000,'truth':truth,
             'models':{'candidate18':base.copy(),'blend75':base.copy(),**{f'residual{a}':base.copy() for a in ResidualMath.ALPHAS}}}
        row['models']['residual0.25']=truth.copy()
        self.assertEqual(ResidualMath.choose([row])['selected']['alpha'],.25)
        with self.assertRaises(ValueError):ResidualMath.choose([{**row,'cutoff':'2026-07-31'}])


if __name__=='__main__':unittest.main()
