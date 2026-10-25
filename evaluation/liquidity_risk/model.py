"""Обучение денежному провалу вместо попытки извлечь риск только из среднего прогноза."""

from datetime import timedelta

import numpy as np

from app.modules.contracts import Direction
from app.modules.forecasting.v2.quality import validate_input
from evaluation.fallback_model.features import DirectFeatures

ALPHAS = np.array([.01, .05, .1, .25, .5, .75, .9, .95, .99])


class ReserveFeatures:
    @staticmethod
    def reserve(flows):
        """Минимальный стартовый остаток для отсутствия отрицательного EOD."""
        values = np.asarray(flows, dtype=np.int64)
        if values.ndim != 2 or values.shape[1] != 2 or len(values) == 0:
            raise ValueError("Нужны дневные поступления/списания")
        return max(0, -int(np.cumsum(values[:, 0] - values[:, 1]).min()))

    @staticmethod
    def make(snapshot):
        data = validate_input(snapshot)
        base, scale, quality = DirectFeatures.make(data)
        days = max(1, min(84, quality.history_days))
        start = data.as_of - timedelta(days=days - 1)
        daily = np.zeros((days, 2), dtype=np.int64)
        for txn in data.txns:
            if start <= txn.booked_on <= data.as_of:
                daily[(txn.booked_on-start).days, 0 if txn.direction == Direction.IN else 1] += txn.amount_minor
        net = (daily[:, 0] - daily[:, 1]).astype(float) / scale
        extra = []
        for window in (7, 14, 28):
            summed = np.convolve(net, np.ones(min(window, days)), mode="valid")
            extra.extend(np.quantile(summed, [.05, .25, .5, .75, .95]).tolist())
            extra.extend([float(np.mean(summed < 0)), float(np.mean(net[-window:]))])
        past_reserves = [ReserveFeatures.reserve(daily[i:i+30]) / scale for i in range(max(0, days-29))]
        extra.extend(np.quantile(past_reserves, [.1, .5, .9]).tolist() if past_reserves else [0., 0., 0.])
        history = [b.closing_balance_minor / scale for b in data.daily_balances if b.balance_date >= start]
        extra.extend([min(history) if history else 0., float(np.mean(np.asarray(history) < 0)) if history else 0.])
        return np.concatenate([base[-1], extra]), scale, quality, np.asarray(past_reserves)


class ReserveModel:
    def __init__(self, depth=4):
        self.depth = depth
        self.model = None

    def fit(self, x, y, weights):
        from catboost import CatBoostRegressor
        self.model = CatBoostRegressor(loss_function="MultiQuantile:alpha=" + ",".join(map(str, ALPHAS)),
                                      iterations=500, depth=self.depth, learning_rate=.04, l2_leaf_reg=8,
                                      random_seed=20261024, thread_count=4, verbose=False, allow_writing_files=False)
        self.model.fit(x, y, sample_weight=weights)
        return self

    def predict_quantiles(self, x):
        raw = np.asarray(self.model.predict(x))
        if not np.isfinite(raw).all():
            raise ValueError("Нечисловые квантили резерва")
        # Пересечения квантилей устраняются до оценки качества, не после неё.
        return np.sort(np.maximum(0, raw), axis=1)

    @staticmethod
    def probability(quantiles, opening):
        quantiles = np.asarray(quantiles, dtype=float)
        if opening < 0:
            return 1.0
        # Для одинаковых квантилей используем правую границу CDF: дефицит строго ниже0.
        unique = np.unique(quantiles)
        probabilities = np.array([ALPHAS[np.where(quantiles == value)[0][-1]] for value in unique])
        cdf = np.interp(opening, unique, probabilities, left=ALPHAS[0]/2, right=(1+ALPHAS[-1])/2)
        return float(np.clip(1-cdf, 0., 1.))

    @staticmethod
    def pinball(y, quantiles):
        residual = np.asarray(y)[:, None] - quantiles
        return float(np.mean(np.maximum(ALPHAS * residual, (ALPHAS-1) * residual)))


class GapClassifier:
    def fit(self, x, labels, weights):
        from catboost import CatBoostClassifier
        self.model = CatBoostClassifier(iterations=500, depth=4, learning_rate=.04, l2_leaf_reg=8,
                                       loss_function="Logloss", random_seed=20261024, thread_count=4,
                                       verbose=False, allow_writing_files=False)
        self.model.fit(x, labels, sample_weight=weights)
        return self

    def predict(self, x):
        return self.model.predict_proba(x)[:, 1]
