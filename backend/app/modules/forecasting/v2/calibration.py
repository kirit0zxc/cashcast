"""Детерминированные калибраторы для заранее разделённых fit/check фаз B6."""

from __future__ import annotations

import math
from dataclasses import dataclass

BIN_EDGES = (0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0)


def _probability(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Ожидается конечная вероятность0–1, None не является нулём")
    return float(value)


def bin_index(probability: float) -> int:
    probability = _probability(probability)
    return next((index for index, edge in enumerate(BIN_EDGES[1:]) if probability < edge), len(BIN_EDGES) - 2)


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)


def _logit(probability: float) -> float:
    clipped = min(1 - 1e-6, max(1e-6, probability))
    return math.log(clipped / (1 - clipped))


@dataclass(frozen=True)
class CalibrationModel:
    kind: str
    parameters: tuple[float, ...] = ()

    def __post_init__(self):
        expected = {"raw": 0, "constant": 1, "logit_intercept": 1, "pava": 6}
        if self.kind not in expected or len(self.parameters) != expected[self.kind]:
            raise ValueError("Неизвестный калибратор/неверные параметры")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in self.parameters):
            raise ValueError("Нечисловой параметр калибратора")
        if self.kind in {"constant", "pava"}:
            for value in self.parameters:
                _probability(value)
        if self.kind == "logit_intercept" and abs(self.parameters[0]) > 40:
            raise ValueError("Смещение калибратора вне диапазона")
        if self.kind == "pava" and any(
            left > right for left, right in zip(self.parameters, self.parameters[1:], strict=False)
        ):
            raise ValueError("Калибратор должен быть монотонным")

    def predict(self, probability: float) -> float:
        probability = _probability(probability)
        if self.kind == "raw":
            return probability
        if self.kind == "constant":
            return self.parameters[0]
        if self.kind == "logit_intercept":
            return _sigmoid(_logit(probability) + self.parameters[0])
        return self.parameters[bin_index(probability)]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "parameters": list(self.parameters)}


def fit_calibrators(observations: list[tuple[float, bool | int]]) -> dict[str, CalibrationModel]:
    if not observations:
        raise ValueError("Пустая fit выборка")
    for probability, actual in observations:
        _probability(probability)
        if type(actual) not in (int, bool) or actual not in (0, 1):
            raise ValueError("Цель должна быть0/1")
    prevalence = (sum(actual for _, actual in observations) + 1) / (len(observations) + 2)
    logits = [_logit(probability) for probability, _ in observations]
    lower, upper = -40.0, 40.0
    for _ in range(100):
        middle = (lower + upper) / 2
        predicted = sum(_sigmoid(logit + middle) for logit in logits) / len(logits)
        if predicted < prevalence:
            lower = middle
        else:
            upper = middle
    counts, positives = [0] * 6, [0] * 6
    for probability, actual in observations:
        index = bin_index(probability)
        counts[index] += 1
        positives[index] += int(actual)
    blocks = []
    for index, (count, positive) in enumerate(zip(counts, positives, strict=True)):
        # Shrink20 к fit-prevalence; пустые bins также имеют явный prior.
        blocks.append(([index], positive + 20 * prevalence, count + 20))
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] > blocks[-1][1] / blocks[-1][2]:
            right, left = blocks.pop(), blocks.pop()
            blocks.append((left[0] + right[0], left[1] + right[1], left[2] + right[2]))
    values = [0.0] * 6
    for indices, positive, count in blocks:
        for index in indices:
            values[index] = positive / count
    return {
        "raw": CalibrationModel("raw"),
        "constant": CalibrationModel("constant", (prevalence,)),
        "logit_intercept": CalibrationModel("logit_intercept", ((lower + upper) / 2,)),
        "pava": CalibrationModel("pava", tuple(values)),
    }
