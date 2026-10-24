"""Сопоставимые денежные ошибки и явная матрица нового отрицательного остатка."""

from collections import defaultdict

import numpy as np


class Score:
    @staticmethod
    def classification(labels, predicted):
        y, p = np.asarray(labels, dtype=bool), np.asarray(predicted, dtype=bool)
        tp, fp = int(np.sum(y & p)), int(np.sum(~y & p))
        fn, tn = int(np.sum(y & ~p)), int(np.sum(~y & ~p))
        return {"n": len(y), "positives": int(y.sum()), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "accuracy": float(np.mean(y == p)) if len(y) else None,
                "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / (tp + fn) if tp + fn else None,
                "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
                "f2": 5 * tp / (5 * tp + fp + 4 * fn) if 5 * tp + fp + 4 * fn else None}

    @staticmethod
    def summarize(rows, key, horizon=30):
        errors, in_errors, out_errors = [], [], []
        daily_labels, daily_predictions, gap_labels, gap_predictions = [], [], [], []
        company_errors, cutoffs = defaultdict(list), defaultdict(list)
        short, established = [], []
        finals = []
        for row in rows:
            truth = row["truth"][:horizon]
            predicted = row["models"][key][:horizon]
            error = (predicted[:, 2] - truth[:, 2]) / 100
            errors.extend(error)
            finals.append(abs(error[-1]))
            in_errors.extend((predicted[:, 0] - truth[:, 0]) / 100)
            out_errors.extend((predicted[:, 1] - truth[:, 1]) / 100)
            company_errors[row["company"]].extend(abs(error))
            cutoffs[row["cutoff"]].extend(abs(error))
            (short if row["cohort"] == "short" else established).extend(abs(error))
            daily_labels.extend(truth[:, 2] < 0)
            daily_predictions.extend(predicted[:, 2] < 0)
            if row["opening"] >= 0:
                gap_labels.append(bool(np.any(truth[:, 2] < 0)))
                gap_predictions.append(bool(np.any(predicted[:, 2] < 0)))
        if not errors:
            return {"windows": 0}
        e = np.asarray(errors)
        return {"windows": len(rows), "days": len(e), "companies": len(company_errors),
                "mae_rub": float(np.mean(abs(e))), "mse_rub2": float(np.mean(e ** 2)),
                "rmse_rub": float(np.sqrt(np.mean(e ** 2))), "final_mae_rub": float(np.mean(finals)),
                "inflow_mae_rub": float(np.mean(np.abs(in_errors))), "outflow_mae_rub": float(np.mean(np.abs(out_errors))),
                "company_macro_mae_rub": float(np.mean([np.mean(v) for v in company_errors.values()])),
                "company_median_mae_rub": float(np.median([np.mean(v) for v in company_errors.values()])),
                "cutoff_mae_rub": {k: float(np.mean(v)) for k, v in cutoffs.items()},
                "cohorts": {"short_history_mae_rub": float(np.mean(short)) if short else None,
                            "established_mae_rub": float(np.mean(established)) if established else None},
                "daily_negative": Score.classification(daily_labels, daily_predictions),
                "new_gap_point": Score.classification(gap_labels, gap_predictions)}

    @staticmethod
    def paired_interval(rows, candidate):
        grouped = defaultdict(list)
        for row in rows:
            truth = row["truth"][:, 2]
            base = np.mean(abs(row["models"]["current"][:, 2] - truth)) / 100
            new = np.mean(abs(row["models"][candidate][:, 2] - truth)) / 100
            grouped[row["company"]].append(new - base)
        if not grouped:
            return None
        values = list(grouped.values())
        rng = np.random.default_rng(20261024)
        differences = []
        for _ in range(500):
            sampled = rng.integers(0, len(values), len(values))
            # Целиком выбираются компании со всеми их окнами, не отдельные дни.
            differences.append(np.mean([v for index in sampled for v in values[index]]))
        return {"difference_mae_rub": float(np.mean([v for x in values for v in x])),
                "ci95_rub": np.quantile(differences, [0.025, 0.975]).tolist(), "resamples": 500,
                "unit": "company", "independent_new_holdout": False}
