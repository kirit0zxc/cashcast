"""Проверяемые метрики без дополнительных ML-зависимостей и неопределённых float."""

from itertools import groupby
from math import sqrt


class EvaluationMetrics:
    @staticmethod
    def value(value, reason=None):
        return {"value": value, "unavailable_reason": reason if value is None else None}

    @classmethod
    def regression(cls, pairs):
        # Внутри приложения копейки; публичные ошибки в рублях и квадратных рублях.
        errors = [(predicted - actual) / 100 for actual, predicted in pairs]
        if not errors:
            return {
                "n": 0,
                **{name: cls.value(None, "Нет сопоставимых фактических значений") for name in ("mae", "mse", "rmse")},
            }
        mse = sum(error * error for error in errors) / len(errors)
        return {
            "n": len(errors),
            "mae": cls.value(sum(map(abs, errors)) / len(errors)),
            "mse": cls.value(mse),
            "rmse": cls.value(sqrt(mse)),
        }

    @classmethod
    def classification(cls, pairs, threshold=0.5, *, probabilities=True):
        # pairs = (факт 0/1, вероятность либо детерминированное предсказание 0/1).
        tp = fp = fn = tn = 0
        for actual, score in pairs:
            predicted = score >= threshold
            tp += int(actual == 1 and predicted)
            fp += int(actual == 0 and predicted)
            fn += int(actual == 1 and not predicted)
            tn += int(actual == 0 and not predicted)
        n = len(pairs)

        def ratio(top, bottom, reason):
            return cls.value(top / bottom if bottom else None, reason)

        metrics = {
            "accuracy": ratio(tp + tn, n, "Нет сопоставимых случаев"),
            "precision": ratio(tp, tp + fp, "Нет положительных предсказаний"),
            "recall": ratio(tp, tp + fn, "Нет положительных фактических случаев"),
            "f1": ratio(2 * tp, 2 * tp + fp + fn, "Нет положительных фактов и предсказаний"),
        }
        if probabilities:
            metrics["brier"] = ratio(
                sum((score - actual) ** 2 for actual, score in pairs), n, "Нет вероятностных предсказаний с фактом"
            )
            positives = tp + fn
            negatives = tn + fp
            # AUC учитывает равные оценки как половину победы, без O(n²).
            wins = lower_negatives = 0
            for _, group in groupby(sorted(pairs, key=lambda x: x[1]), key=lambda x: x[1]):
                labels = [actual for actual, _ in group]
                pos = sum(labels)
                neg = len(labels) - pos
                wins += pos * (lower_negatives + neg / 2)
                lower_negatives += neg
            metrics["roc_auc"] = ratio(wins, positives * negatives, "Нужны оба фактических класса")
            # AP — ступенчатый интеграл precision-recall, группы равных оценок целиком.
            cumulative_tp = cumulative_n = 0
            ap = 0.0
            for _, group in groupby(sorted(pairs, key=lambda x: -x[1]), key=lambda x: x[1]):
                labels = [actual for actual, _ in group]
                found = sum(labels)
                cumulative_tp += found
                cumulative_n += len(labels)
                ap += found * cumulative_tp / cumulative_n
            metrics["average_precision"] = ratio(ap, positives, "Нет положительных фактических случаев")
        return {
            "n": n,
            "threshold": threshold,
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "metrics": metrics,
        }
