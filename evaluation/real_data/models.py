"""Кандидат учится только на прошлом; рекурсивные лаги строятся из его прогнозов."""

from datetime import timedelta
from statistics import mean

from .datasets import Day

SEED = 20261024


class FlowFeatures:
    @staticmethod
    def make(history: list[Day], target):
        if len(history) < 84 or history[-1].date + timedelta(days=1) != target:
            raise ValueError("Нужны 84 дня непрерывной истории перед целью")
        result = [target.weekday(), target.day, target.month]
        for attr in ("incoming", "outgoing"):
            values = [getattr(d, attr) / 100 for d in history[-84:]]
            result.extend(values[-lag] for lag in (1, 7, 14, 28))
            result.extend(mean(values[-window:]) for window in (7, 28, 84))
        return result


class FlowCandidate:
    VERSION = "research-catboost-flows-v1"

    def fit(self, history: list[Day]):
        # Зависимость нужна только для исследовательского запуска, не для API/worker.
        from catboost import CatBoostRegressor

        x = [
            FlowFeatures.make(history[i - 84 : i], history[i].date)
            for i in range(84, len(history))
        ]
        self.models = []
        for attr in ("incoming", "outgoing"):
            model = CatBoostRegressor(
                iterations=300,
                depth=4,
                learning_rate=0.04,
                loss_function="RMSE",
                random_seed=SEED,
                thread_count=2,
                verbose=False,
                allow_writing_files=False,
            )
            model.fit(x, [getattr(d, attr) / 100 for d in history[84:]])
            self.models.append(model)
        return self

    def predict(self, history: list[Day], horizon: int):
        working = list(history[-84:])
        future = []
        for _ in range(horizon):
            target = working[-1].date + timedelta(days=1)
            features = FlowFeatures.make(working, target)
            incoming, outgoing = [
                max(0, round(float(m.predict([features])[0]) * 100))
                for m in self.models
            ]
            point = Day(
                target, incoming, outgoing, working[-1].balance + incoming - outgoing
            )
            working.append(point)
            future.append(point)
        return future


class FlowBaseline:
    def __init__(self, mode):
        if mode not in {"last_week", "weekday84"}:
            raise ValueError("Неизвестный ориентир")
        self.mode = mode

    def predict(self, history: list[Day], horizon: int):
        working = list(history)
        future = []
        for offset in range(horizon):
            day = history[-1].date + timedelta(days=offset + 1)
            samples = (
                [working[-7]]
                if self.mode == "last_week"
                else [d for d in history[-84:] if d.date.weekday() == day.weekday()]
            )
            incoming = round(mean(d.incoming for d in samples))
            outgoing = round(mean(d.outgoing for d in samples))
            point = Day(
                day, incoming, outgoing, working[-1].balance + incoming - outgoing
            )
            working.append(point)
            future.append(point)
        return future
