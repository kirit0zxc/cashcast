"""Условный риск превышения резервом порога, без подмены реального баланса."""
from collections import Counter

import numpy as np

from .model import ReserveFeatures

GRID = (0., .25, .5, 1., 2., 4., 8., 16., 32., 64.)
HORIZONS = (7, 14, 30)


class DistributionQueries:
    @staticmethod
    def query(features, horizon, threshold):
        if horizon not in HORIZONS or not np.isfinite(threshold) or threshold<0:
            raise ValueError("Непригодный запрос к распределению резерва")
        features=np.asarray(features,dtype=float)
        if features.ndim!=1 or not np.isfinite(features).all():
            raise ValueError("Непригодные прошлые признаки")
        # Исторический opening в features не меняем: порог — отдельный запрос.
        return np.r_[features, horizon/30., np.log1p(threshold)]

    @classmethod
    def augment(cls,rows):
        counts=Counter(r["company"] for r in rows)
        x,y,weights=[],[],[]
        for row in rows:
            grid=sorted(set(GRID+(max(0.,row["opening"]),)))
            weight=1/(len(counts)*counts[row["company"]]*len(HORIZONS)*len(grid))
            for horizon in HORIZONS:
                reserve=ReserveFeatures.reserve(row["truth"][:horizon,:2])/row["scale"]
                for threshold in grid:
                    x.append(cls.query(row["features"],horizon,threshold))
                    y.append(int(reserve>threshold))
                    weights.append(weight)
        values=np.asarray(weights)
        return np.asarray(x),np.asarray(y),values/values.mean()


class DistributionModel:
    def __init__(self,depth=4,iterations=600):
        self.depth,self.iterations=depth,iterations
        self.model=None

    def fit(self,x,y,weights):
        from catboost import CatBoostClassifier
        self.model=CatBoostClassifier(iterations=self.iterations,depth=self.depth,
            learning_rate=.04,l2_leaf_reg=8,loss_function="Logloss",random_seed=20261025,
            thread_count=4,verbose=False,allow_writing_files=False,
            monotone_constraints={x.shape[1]-2:1,x.shape[1]-1:-1})
        self.model.fit(x,y,sample_weight=weights)
        return self

    def predict(self,queries):
        if self.model is None: raise RuntimeError("Распределение ещё не обучено")
        values=self.model.predict_proba(np.asarray(queries))[:,1]
        if not np.isfinite(values).all() or np.any((values<0)|(values>1)):
            raise ValueError("Непригодная вероятность модели")
        return values
