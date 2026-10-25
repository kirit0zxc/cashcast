"""Метрики: формулы MAE/MSE/RMSE и матриц те же, что в «Проверке качества» стека."""

import math
import random
from collections import defaultdict

import numpy as np

from app.modules.evaluation.metrics import EvaluationMetrics

from .features import scale

SEED = 42
GRID = tuple(round(x, 2) for x in np.arange(0.05, 0.96, 0.05))
# Нормированная MAE как в аудите: ошибка окна / max(10 000 ₽, средний дневной приток или отток за 84 дня).
NORM_FLOOR_MINOR = 1_000_000
BUCKETS = {"1-7": slice(0, 7), "8-14": slice(7, 14), "15-30": slice(14, 30)}


def _flat(report):
    # {"value": x, "unavailable_reason": ...} -> x; причина недоступности сохраняется отдельно.
    return {key: (value["value"] if isinstance(value, dict) and "value" in value else value)
            for key, value in report.items()}


def regression(rows):
    """rows: [(window, prediction)] — остаток/потоки в копейках, ошибки в рублях."""
    truth = np.array([w.truth for w, _ in rows])  # (n, 30, 3)
    p50 = np.array([p["p50"] for _, p in rows])
    inc = np.array([p["inc"] for _, p in rows])
    out = np.array([p["out"] for _, p in rows])
    y = truth[:, :, 2]
    error = p50 - y
    window_abs = np.abs(error).sum(axis=1)
    norm = np.array([max(NORM_FLOOR_MINOR, scale(w)) for w, _ in rows])
    report = {
        "windows": len(rows),
        "days": int(error.size),
        "balance": _flat(EvaluationMetrics.regression(list(zip(y.ravel(), p50.ravel(), strict=True)))),
        "inflow": _flat(EvaluationMetrics.regression(list(zip(truth[:, :, 0].ravel(), inc.ravel(), strict=True)))),
        "outflow": _flat(EvaluationMetrics.regression(list(zip(truth[:, :, 1].ravel(), out.ravel(), strict=True)))),
        "balance_mae_end_rub": float(np.abs(error[:, -1]).mean() / 100),
        "balance_bias_rub": float(error.mean() / 100),
        "balance_wape": float(np.abs(error).sum() / np.abs(y).sum()),
        "inflow_wape": float(np.abs(inc - truth[:, :, 0]).sum() / max(truth[:, :, 0].sum(), 1)),
        "outflow_wape": float(np.abs(out - truth[:, :, 1]).sum() / max(truth[:, :, 1].sum(), 1)),
        "balance_mae_by_day_rub": (np.abs(error).mean(axis=0) / 100).round(2).tolist(),
        "balance_r2": float(1 - (error ** 2).sum() / ((y - y.mean()) ** 2).sum()),
        "balance_normalized_mae": float(np.mean(np.abs(error).mean(axis=1) / norm)),
        "top5_windows_error_share": float(np.sort(window_abs)[-5:].sum() / window_abs.sum()),
    }
    if all(p["p10"] is not None for _, p in rows):
        p10 = np.array([p["p10"] for _, p in rows])
        p90 = np.array([p["p90"] for _, p in rows])
        inside = (p10 <= y) & (y <= p90)
        report["coverage_p10_p90"] = float(inside.mean())
        report["coverage_by_horizon"] = {k: float(inside[:, s].mean()) for k, s in BUCKETS.items()}
        report["interval_width_rub"] = float((p90 - p10).mean() / 100)
        # Interval score для центрального 80% интервала (alpha = 0.2), рубли.
        score = (p90 - p10) + 10 * np.maximum(p10 - y, 0) + 10 * np.maximum(y - p90, 0)
        report["interval_score_rub"] = float(score.mean() / 100)

        def pinball(q, alpha):
            diff = y - q
            return np.maximum(alpha * diff, (alpha - 1) * diff).mean() / 100

        report["pinball_mean_rub"] = float((pinball(p10, 0.1) + pinball(p50, 0.5) + pinball(p90, 0.9)) / 3)
    # Ежедневный минус по медиане — отдельная единица наблюдения (день), как в стеке.
    daily = list(zip((y < 0).astype(int).ravel(), (p50 < 0).astype(int).ravel(), strict=True))
    report["daily_negative_by_median"] = _classification(daily, 0.5, probabilities=False)
    return report


def _classification(pairs, threshold, probabilities=True):
    raw = EvaluationMetrics.classification([(int(a), float(s)) for a, s in pairs], threshold,
                                           probabilities=probabilities)
    matrix = raw["confusion_matrix"]
    tp, fp, fn, tn = (matrix[k] for k in ("tp", "fp", "fn", "tn"))
    metrics = _flat(raw["metrics"])
    tpr = tp / (tp + fn) if tp + fn else None
    tnr = tn / (tn + fp) if tn + fp else None
    metrics["balanced_accuracy"] = (tpr + tnr) / 2 if tpr is not None and tnr is not None else None
    if probabilities and pairs:
        clipped = [(a, min(max(s, 1e-12), 1 - 1e-12)) for a, s in pairs]
        metrics["log_loss"] = -sum(a * math.log(s) + (1 - a) * math.log(1 - s) for a, s in clipped) / len(pairs)
        metrics["share_probability_exact_0_or_1"] = sum(s in (0.0, 1.0) for _, s in pairs) / len(pairs)
    return {"n": raw["n"], "positives": tp + fn, "threshold": threshold, "confusion_matrix": matrix,
            "metrics": metrics}


def choose_threshold(pairs):
    """Порог выбирается только на validation: максимум F1, при равенстве — более высокий порог."""
    best = None
    for threshold in GRID:
        f1 = _classification(pairs, threshold, probabilities=False)["metrics"]["f1"] or 0.0
        if best is None or f1 >= best[0]:
            best = (f1, threshold)
    return best[1]


def risk(pairs, threshold):
    return {"at_0_5": _classification(pairs, 0.5), "at_validation_threshold": _classification(pairs, threshold)}


def _company_sums(items):
    """items: [(company, сумма потерь окна, число единиц)] -> {company: [сумма, число]}."""
    sums = defaultdict(lambda: [0.0, 0])
    for company, loss, count in items:
        sums[company][0] += loss
        sums[company][1] += count
    return sums


def _bootstrap(new, old, repetitions, scale_by):
    companies = sorted(new)
    if not companies:
        return {"estimate": None, "ci95": [None, None], "companies_better": 0, "companies": 0, "unit": "company",
                "repetitions": repetitions, "negative_favors_new": True}
    rng = random.Random(SEED)  # noqa: S311 — воспроизводимый bootstrap
    values = []
    for _ in range(repetitions):
        draw = [companies[rng.randrange(len(companies))] for _ in companies]
        n = sum(new[c][1] for c in draw)
        values.append((sum(new[c][0] for c in draw) - sum(old[c][0] for c in draw)) / n / scale_by)
    values.sort()
    n = sum(new[c][1] for c in companies)
    estimate = (sum(new[c][0] for c in companies) - sum(old[c][0] for c in companies)) / n / scale_by
    wins = sum(new[c][0] / new[c][1] < old[c][0] / old[c][1] for c in companies)
    return {"estimate": estimate, "ci95": [values[int(0.025 * repetitions)], values[int(0.975 * repetitions) - 1]],
            "companies_better": wins, "companies": len(companies), "unit": "company",
            "repetitions": repetitions, "negative_favors_new": True}


def paired_bootstrap(rows_new, rows_old, repetitions=2000):
    """Разность MAE остатка (новая − эталон) в рублях; пересэмплируются целые компании."""
    def sums(rows):
        return _company_sums((w.company, float(np.abs(p["p50"] - w.truth[:, 2]).sum()), len(w.truth))
                             for w, p in rows)
    return _bootstrap(sums(rows_new), sums(rows_old), repetitions, 100)


def paired_brier_bootstrap(items_new, items_old, repetitions=2000):
    """items: [(company, метка, вероятность)] — разность Brier (новая − эталон)."""
    def sums(items):
        return _company_sums((c, (s - y) ** 2, 1) for c, y, s in items)
    return _bootstrap(sums(items_new), sums(items_old), repetitions, 1)


def curves(pairs):
    """Точки ROC/PR и калибровки для графиков (агрегаты, без исходных строк)."""
    if not pairs:
        return {"roc": [[0.0, 0.0], [1.0, 1.0]], "pr": [[0.0, 1.0]], "prevalence": 0.0, "calibration": []}
    labels = np.array([a for a, _ in pairs])
    scores = np.array([s for _, s in pairs])
    order = np.argsort(-scores, kind="stable")
    labels, scores = labels[order], scores[order]
    # Равные оценки — одна точка кривой: порядок строк не должен рисовать ступеньки.
    last = np.r_[scores[1:] != scores[:-1], True]
    tps, fps = np.cumsum(labels)[last], np.cumsum(1 - labels)[last]
    positives, negatives = max(labels.sum(), 1), max((1 - labels).sum(), 1)
    bins = np.linspace(0, 1, 11)
    which = np.clip(np.digitize(scores, bins) - 1, 0, 9)
    calibration = [[float(scores[which == b].mean()), float(labels[which == b].mean()), int((which == b).sum())]
                   for b in range(10) if (which == b).any()]
    return {
        "roc": [[0.0, 0.0], *zip((fps / negatives).round(4).tolist(), (tps / positives).round(4).tolist(),
                                 strict=True)],
        "pr": [[0.0, 1.0], *zip((tps / positives).round(4).tolist(), (tps / (tps + fps)).round(4).tolist(),
                                strict=True)],
        "prevalence": float(labels.mean()) if len(labels) else None,
        "calibration": calibration,
    }
