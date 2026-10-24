"""Метрики риска и выбор порога на calibration-check, без замены None нулём."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from itertools import pairwise
from statistics import mean

from app.modules.forecasting.v2.calibration import BIN_EDGES, bin_index

THRESHOLDS = (0.05, 0.1, 0.2, 0.3, 0.5)


def wilson(success: int, count: int):
    if not count:
        return None
    z = 1.959963984540054
    p = success / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    half = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0, center - half), min(1, center + half)]


def classification(rows, threshold: float):
    tp = sum(row["probability"] >= threshold and row["actual"] for row in rows)
    fp = sum(row["probability"] >= threshold and not row["actual"] for row in rows)
    fn = sum(row["probability"] < threshold and row["actual"] for row in rows)
    tn = len(rows) - tp - fp - fn
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_alarm_rate": fp / (fp + tn) if fp + tn else None,
        "f2": 5 * tp / (5 * tp + 4 * fn + fp) if tp + fn + fp else 0.0,
        "precision_wilson95": wilson(tp, tp + fp),
        "recall_wilson95": wilson(tp, tp + fn),
        "false_alarm_rate_wilson95": wilson(fp, fp + tn),
    }


def choose_threshold(rows):
    candidates = [classification(rows, threshold) for threshold in THRESHOLDS]
    feasible = [
        value for value in candidates if value["false_alarm_rate"] is not None and value["false_alarm_rate"] <= 0.25
    ]
    selected = max(feasible, key=lambda value: (value["f2"], value["threshold"])) if feasible else None
    return {"selected": selected, "candidates": candidates, "false_alarm_definition": "FP/(FP+TN)"}


def report(rows, threshold=None):
    if any(row["probability"] is None for row in rows):
        raise ValueError("None наблюдения должны быть раскрыты отдельно, не заменены нулём")
    if not rows:
        return {"observations": 0, "brier": None, "positives": 0, "companies": 0, "reliability": []}
    bins = []
    for index, (lower, upper) in enumerate(pairwise(BIN_EDGES)):
        selected = [row for row in rows if bin_index(row["probability"]) == index]
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(selected),
                "mean_probability": mean(row["probability"] for row in selected) if selected else None,
                "frequency": mean(row["actual"] for row in selected) if selected else None,
                "frequency_wilson95": wilson(sum(row["actual"] for row in selected), len(selected)),
            }
        )
    output = {
        "observations": len(rows),
        "companies": len({row["company"] for row in rows}),
        "positives": sum(row["actual"] for row in rows),
        "positive_companies": len({row["company"] for row in rows if row["actual"]}),
        "frequency": mean(row["actual"] for row in rows),
        "brier": mean((row["probability"] - row["actual"]) ** 2 for row in rows),
        "reliability": bins,
        "ece": sum(
            value["count"] * abs(value["mean_probability"] - value["frequency"]) for value in bins if value["count"]
        )
        / len(rows),
    }
    if threshold is not None:
        output["classification"] = classification(rows, threshold)
        # Горизонтный alert доступен на as_of; lead_days — время до первого фактического минуса.
        leads = [
            row["lead_days"]
            for row in rows
            if row["actual"] and row["probability"] >= threshold and row.get("lead_days") is not None
        ]
        output["true_alert_lead_days"] = {
            "count": len(leads),
            "mean": mean(leads) if leads else None,
            "min": min(leads) if leads else None,
            "max": max(leads) if leads else None,
        }
    return output


def paired_company_bootstrap(rows, other, repetitions=500):
    if len(rows) != len(other) or any(
        (left["company"], left["key"], left["actual"]) != (right["company"], right["key"], right["actual"])
        for left, right in zip(rows, other, strict=True)
    ):
        raise ValueError("Bootstrap требует одинаковые парные наблюдения")
    grouped = defaultdict(list)
    for left, right in zip(rows, other, strict=True):
        grouped[left["company"]].append(
            (left["probability"] - left["actual"]) ** 2 - (right["probability"] - right["actual"]) ** 2
        )
    if not grouped:
        return {"companies": 0, "difference_brier": None, "ci95": None}
    companies = sorted(grouped)
    aggregates = {company: (sum(grouped[company]), len(grouped[company])) for company in companies}
    rng = random.Random(20261024)  # noqa: S311 -- воспроизводимое перевыборивание компаний
    values = []
    for _ in range(repetitions):
        sample = rng.choices(companies, k=len(companies))
        values.append(
            sum(aggregates[company][0] for company in sample) / sum(aggregates[company][1] for company in sample)
        )
    values.sort()
    return {
        "companies": len(companies),
        "difference_brier": mean(value for group in grouped.values() for value in group),
        "ci95": [values[int(0.025 * (repetitions - 1))], values[int(0.975 * (repetitions - 1))]],
        "repetitions": repetitions,
        "unit": "company",
        "seed": 20261024,
    }
