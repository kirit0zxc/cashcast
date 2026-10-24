"""Bootstrap по счетам: зависимые окна одного счёта переносятся вместе."""

import random
from collections import defaultdict


def interval(values, repetitions):
    ordered = sorted(v for v in values if v is not None)
    return {
        "ci95": [ordered[int(0.025 * (len(ordered) - 1))], ordered[int(0.975 * (len(ordered) - 1))]]
        if ordered
        else None,
        "valid_repetitions": len(ordered),
        "undefined_repetitions": repetitions - len(ordered),
    }


def account_bootstrap(accounts, labels, scores, threshold, prior, repetitions=500):
    if not (len(accounts) == len(labels) == len(scores)) or not accounts or repetitions <= 0:
        raise ValueError("Нужны непустые парные наблюдения и положительное число повторов")
    groups = defaultdict(lambda: [0, 0, 0, 0, 0.0])
    for account, y, s in zip(accounts, labels, scores, strict=True):
        row = groups[account]
        row[0] += 1
        row[1] += int(y and s >= threshold)
        row[2] += int(not y and s >= threshold)
        row[3] += int(y and s < threshold)
        row[4] += (s - y) ** 2 - (prior - y) ** 2
    ordered = [groups[key] for key in sorted(groups)]
    rng = random.Random(20261024)
    differences, precisions, recalls = [], [], []
    for _ in range(repetitions):
        sample = [ordered[rng.randrange(len(ordered))] for _ in ordered]
        n, tp, fp, fn, delta = [sum(row[i] for row in sample) for i in range(5)]
        differences.append(delta / n)
        precisions.append(tp / (tp + fp) if tp + fp else None)
        recalls.append(tp / (tp + fn) if tp + fn else None)
    return {
        "unit": "account",
        "accounts": len(groups),
        "repetitions": repetitions,
        "seed": 20261024,
        "brier_minus_constant": interval(differences, repetitions),
        "precision": interval(precisions, repetitions),
        "recall": interval(recalls, repetitions),
    }
