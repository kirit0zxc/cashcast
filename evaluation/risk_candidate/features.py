"""Признаки ликвидности только из доступных 84 дней истории."""

from statistics import mean

from evaluation.real_data.risk import features


class LiquidityFeatures:
    @staticmethod
    def build(history):
        if len(history) != 84:
            raise ValueError("Требуется ровно 84 прошлых дня")
        scale = max(100, mean(day.outgoing for day in history))
        last = history[-1]
        values = features(history)
        for lag in (7, 28, 83):
            values.append((last.balance - history[-1 - lag].balance) / scale)
        for window in (7, 28):
            balances = [day.balance for day in history[-window:]]
            values.extend((min(balances) / scale, mean(balances) / scale))
        since_income = next((i for i, day in enumerate(reversed(history)) if day.incoming > 0), 84)
        expenses = sorted(day.outgoing for day in history)
        values.extend((since_income, sum(d.incoming > 0 for d in history) / 84,
                       sum(d.outgoing > 0 for d in history) / 84, expenses[75] / scale,
                       last.outgoing / scale))
        return values
