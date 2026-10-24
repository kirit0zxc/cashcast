"""Калибровка и явный отказ от публикации предупреждений при слабом качестве."""

import math
from statistics import mean

from evaluation.real_data.risk import metrics

THRESHOLDS = (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5)
BIN_EDGES = (0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1)


def validate(labels, scores):
    if len(labels) != len(scores) or not labels:
        raise ValueError("Нужны непустые парные метки и оценки")
    if any(y not in (0, 1) for y in labels):
        raise ValueError("Метки должны быть бинарными")
    if any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
        raise ValueError("Оценки должны быть конечными от 0 до 1")


class InterceptCalibrator:
    def __init__(self, intercept):
        self.intercept = intercept

    @staticmethod
    def shifted(score, intercept):
        # Граница только для logit; исходный score не переписывается.
        score = min(1 - 1e-12, max(1e-12, score))
        z = math.log(score) - math.log1p(-score) + intercept
        return 1 / (1 + math.exp(-z))

    @classmethod
    def fit(cls, labels, scores):
        validate(labels, scores)
        if len(labels) < 1000 or min(sum(labels), len(labels) - sum(labels)) < 10:
            return None
        low, high = -20.0, 20.0
        target = mean(labels)
        for _ in range(100):
            middle = (low + high) / 2
            if mean(cls.shifted(s, middle) for s in scores) < target:
                low = middle
            else:
                high = middle
        return cls((low + high) / 2)

    def transform(self, scores):
        if any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
            raise ValueError("Некорректные оценки")
        return [self.shifted(s, self.intercept) for s in scores]


def reliability(labels, scores):
    validate(labels, scores)
    output = []
    for i, (lower, upper) in enumerate(zip(BIN_EDGES, BIN_EDGES[1:])):
        ids = [j for j, s in enumerate(scores) if lower <= s and (s < upper or i == len(BIN_EDGES) - 2)]
        output.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(ids),
                "mean_score": mean(scores[j] for j in ids) if ids else None,
                "observed_frequency": mean(labels[j] for j in ids) if ids else None,
            }
        )
    return output


def choose_operating_point(labels, scores, prior):
    validate(labels, scores)
    candidates = []
    for threshold in THRESHOLDS:
        result = metrics(labels, scores, threshold, prior)
        result["threshold"] = threshold
        result["f1"] = 2 * result["tp"] / (2 * result["tp"] + result["fp"] + result["fn"]) if result["tp"] else 0.0
        candidates.append(result)
    eligible = [
        r
        for r in candidates
        if r["positives"] >= 10
        and r["precision"] is not None
        and r["precision"] >= 0.5
        and r["recall"] is not None
        and r["recall"] >= 0.5
        and r["fpr"] is not None
        and r["fpr"] <= 0.01
    ]
    selected = max(eligible, key=lambda r: (r["f1"], -r["fp"], r["threshold"])) if eligible else None
    return {
        "selected": selected,
        "candidates": candidates,
        "reason": "criteria_met" if selected else "no_threshold_meets_policy",
    }
