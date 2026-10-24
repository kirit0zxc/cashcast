"""Проверки расширенных запросов к резерву и реальных монотонных весов."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from evaluation.liquidity_risk.distribution_run import DistributionExperiment
from evaluation.liquidity_risk.distribution import DistributionModel,DistributionQueries,HORIZONS


class DistributionTests(unittest.TestCase):
    @staticmethod
    def rows():
        flows=np.tile([20,30],(30,1))
        truth=np.column_stack([flows,400+np.cumsum(flows[:,0]-flows[:,1])])
        return [{'company':'a','features':np.array([1.,2.,3.]),'opening':4.,'scale':100.,'truth':truth},
                {'company':'b','features':np.array([2.,3.,4.]),'opening':4.,'scale':100.,'truth':truth}]

    def test_query_does_not_change_history(self):
        features=np.array([1.,2.,3.]);old=features.copy()
        q=DistributionQueries.query(features,7,10)
        np.testing.assert_array_equal(features,old)
        np.testing.assert_array_equal(q[:-2],old)

    def test_grid_does_not_read_future_reserve(self):
        rows=self.rows();x,y,w=DistributionQueries.augment(rows)
        rows[0]['truth'][:,:2]=0
        changed,labels,weights=DistributionQueries.augment(rows)
        np.testing.assert_array_equal(x,changed)
        np.testing.assert_array_equal(w,weights)
        self.assertFalse(np.array_equal(y,labels))

    def test_each_company_equal_weight(self):
        rows=self.rows();rows.append(dict(rows[0],opening=3.7))
        x,y,w=DistributionQueries.augment(rows)
        # Запросы с features[0]==1 принадлежат a, с==2 — b.
        self.assertAlmostEqual(float(w[x[:,0]==1].sum()),float(w[x[:,0]==2].sum()))

    def test_zero_reserve_never_exceeds_zero(self):
        rows=self.rows()
        for row in rows: row['truth'][:,:2]=0
        self.assertEqual(int(DistributionQueries.augment(rows)[1].sum()),0)

    def test_invalid_queries_rejected(self):
        for horizon,threshold in ((1,1),(7,-1),(30,np.nan),(14,np.inf)):
            with self.assertRaises(ValueError): DistributionQueries.query([1],horizon,threshold)

    def test_real_model_monotonic_and_reload(self):
        from catboost import CatBoostClassifier
        x,y,w=DistributionQueries.augment(self.rows())
        model=DistributionModel(depth=2,iterations=40).fit(x,y,w)
        query=[DistributionQueries.query([1.,2.,3.],h,q) for h in HORIZONS for q in np.linspace(0,10,101)]
        prediction=model.predict(query).reshape(3,101)
        self.assertTrue(np.all(np.diff(prediction,axis=1)<=1e-10))
        self.assertTrue(np.all(np.diff(prediction,axis=0)>=-1e-10))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.cbm';model.model.save_model(str(path))
            restored=DistributionModel();restored.model=CatBoostClassifier();restored.model.load_model(str(path))
            np.testing.assert_allclose(restored.predict(query),prediction.ravel(),rtol=0,atol=1e-14)

    def test_natural_statistics_uses_bool_labels_safely(self):
        runner=object.__new__(DistributionExperiment)
        runner.priors={'30':.1}
        rows=self.rows()
        for row in rows: row.update(current=.2,scores={'cdf4':{'30':.2}})
        report=runner.statistics(rows,'cdf4')
        self.assertTrue(np.isfinite(report['log_loss']))
        self.assertEqual(report['positives'],0)


if __name__=='__main__': unittest.main()
