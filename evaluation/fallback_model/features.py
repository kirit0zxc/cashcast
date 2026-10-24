"""Признаки прямого прогноза: только прошлые деньги и известный календарь."""

from calendar import monthrange
from datetime import timedelta

import numpy as np

from app.modules.contracts import Direction
from app.modules.forecasting.v2.quality import assess_quality, validate_input


class DirectFeatures:
    """Одинаковое преобразование при обучении и в локальном адаптере."""

    @staticmethod
    def make(data):
        data = validate_input(data)
        quality = assess_quality(data)
        days = max(1, min(84, quality.history_days))
        start = data.as_of - timedelta(days=days - 1)
        daily = np.zeros((days, 2), dtype=float)
        for txn in data.txns:
            if start <= txn.booked_on <= data.as_of:
                daily[(txn.booked_on - start).days, 0 if txn.direction == Direction.IN else 1] += txn.amount_minor
        # Один масштаб денежных потоков, вычисленный исключительно из истории.
        scale = max(100.0, float(daily.sum(axis=1).mean()))
        normalized = daily / scale
        dates = [start + timedelta(days=i) for i in range(days)]
        past_weekdays = np.array([day.weekday() for day in dates])
        features = [days, quality.reconciliation_breaks, data.opening_balance_minor / scale]
        for direction in range(2):
            values = normalized[:, direction]
            for window in (7, 14, 28, 56, 84):
                sample = values[-window:]
                features.extend([sample.mean(), sample.std(), np.mean(sample == 0), sample.max()])
            for lag in (1, 7, 14, 28):
                features.append(values[-lag] if len(values) >= lag else 0.0)
        weekday_means = np.array([
            normalized[past_weekdays == day].mean(axis=0) if np.any(past_weekdays == day) else normalized.mean(axis=0)
            for day in range(7)
        ])
        rows = []
        cumulative_weekday = np.zeros(2)
        calendar_counts = np.zeros(7)
        for h in range(1, data.horizon_days + 1):
            target = data.as_of + timedelta(days=h)
            cumulative_weekday += weekday_means[target.weekday()]
            calendar_counts[target.weekday()] += 1
            rows.append(features + [h, data.as_of.day, data.as_of.weekday(), target.day,
                                   target.weekday(), target.month, monthrange(target.year, target.month)[1] - target.day]
                        + (cumulative_weekday / h).tolist() + (calendar_counts / h).tolist())
        return np.asarray(rows, dtype=float), scale, quality


class DirectCandidate:
    """Одна модель с двумя целями, предсказывающая каждый горизонт непосредственно."""

    def __init__(self, depth=4):
        self.depth = depth
        self.model = None

    def fit(self, x, y, weights):
        from catboost import CatBoostRegressor
        self.model = CatBoostRegressor(iterations=500, depth=self.depth, learning_rate=0.04,
                                      loss_function="MultiRMSE", l2_leaf_reg=8, random_seed=20261024,
                                      thread_count=4, verbose=False, allow_writing_files=False)
        self.model.fit(x, y, sample_weight=weights)
        return self

    def predict(self, data):
        if self.model is None:
            raise RuntimeError("Кандидат ещё не обучен")
        x, scale, quality = DirectFeatures.make(data)
        raw = np.asarray(self.model.predict(x), dtype=float)
        if not np.isfinite(raw).all():
            raise ValueError("Модель вернула нечисловые суммы")
        cumulative = np.maximum.accumulate(np.maximum(0, raw) * scale * np.arange(1, len(x) + 1)[:, None], axis=0)
        cumulative = np.rint(cumulative).astype(np.int64)
        flows = np.diff(cumulative, axis=0, prepend=np.zeros((1, 2), dtype=np.int64))
        balance = data.opening_balance_minor + cumulative[:, 0] - cumulative[:, 1]
        return flows, balance, scale, quality
