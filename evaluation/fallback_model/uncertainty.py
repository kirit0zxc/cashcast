"""Целые траектории ошибок прошлых прогнозов; вероятности требуют отдельной проверки."""

import json
import pickle
from collections import Counter
from pathlib import Path

import numpy as np

from evaluation.real_data.risk import metrics
from .metrics import Score


class ErrorTrajectories:
    def __init__(self, paths):
        paths = np.asarray(paths, dtype=float)
        if paths.shape != (200, 30) or not np.isfinite(paths).all():
            raise ValueError("Неверная библиотека локальных траекторий")
        self.paths = paths

    @classmethod
    def fit(cls, rows, key):
        eligible = [row for row in rows if row["current_probability"] is not None]
        if not eligible:
            raise ValueError("Нет пригодных прошлых ошибок")
        owners = Counter(row["company"] for row in eligible)
        weights = np.array([1 / owners[row["company"]] for row in eligible])
        weights /= weights.sum()
        indices = np.random.default_rng(20261024).choice(len(eligible), 200, replace=True, p=weights)
        paths = np.array([(eligible[i]["truth"][:, 2] - eligible[i]["models"][key][:, 2]) / eligible[i]["scale"] for i in indices])
        paths -= np.median(paths, axis=0)
        return cls(paths)

    def predict(self, balance, scale):
        paths = np.asarray(balance)[None, :] + self.paths[:, :len(balance)] * scale
        daily = (np.sum(paths < 0, axis=0) + 0.5) / (len(paths) + 1)
        union = (np.sum(np.any(paths < 0, axis=1)) + 0.5) / (len(paths) + 1)
        return {"daily": daily, "union": float(union), "lower": np.quantile(paths, 0.1, axis=0),
                "upper": np.quantile(paths, 0.9, axis=0)}


class ProbabilityStudy:
    @staticmethod
    def evaluate(rows, key, estimator, threshold, prior):
        labels, predicted, current = [], [], []
        daily_labels, daily_scores, coverage = [], [], []
        unavailable = 0
        for row in rows:
            if row["current_probability"] is None:
                unavailable += 1
                continue
            estimate = estimator.predict(row["models"][key][:, 2], row["scale"])
            truth = row["truth"][:, 2]
            daily_labels.extend(truth < 0)
            daily_scores.extend(estimate["daily"])
            coverage.extend((truth >= estimate["lower"]) & (truth <= estimate["upper"]))
            if row["opening"] >= 0:
                labels.append(bool(np.any(truth < 0)))
                predicted.append(estimate["union"])
                current.append(row["current_probability"])
        def report(y, p):
            return {**metrics(y, p, threshold, prior), **Score.classification(y, np.asarray(p) >= threshold)}
        reliability = []
        for left, right in zip([0, .1, .2, .4, .6, .8], [.1, .2, .4, .6, .8, 1.000001]):
            selected = [(p, y) for p, y in zip(predicted, labels) if left <= p < right]
            if selected:
                reliability.append({"lower": left, "upper": min(1, right), "n": len(selected),
                                    "mean_probability": float(np.mean([p for p, _ in selected])),
                                    "observed_rate": float(np.mean([y for _, y in selected]))})
        return {"candidate": report(labels, predicted), "current": report(labels, current),
                "daily_candidate": report(daily_labels, daily_scores),
                "interval_coverage": float(np.mean(coverage)) if coverage else None,
                "unavailable_windows": unavailable, "reliability": reliability, "threshold": threshold}

    @classmethod
    def run(cls, output):
        report = json.loads((output / "results.json").read_text(encoding="utf-8"))
        key = report["selection"]["selected"]
        # pickle загружается только из собственного локального запуска, не из входного ZIP.
        def read(name):
            with (output / f"{name}.pickle").open("rb") as stream:
                return pickle.load(stream)
        fit = read("calibration")
        estimator = ErrorTrajectories.fit(fit, key)
        labels = [bool(np.any(row["truth"][:, 2] < 0)) for row in fit
                  if row["opening"] >= 0 and row["current_probability"] is not None]
        prior = (sum(labels) + 0.5) / (len(labels) + 1)
        check = read("calibration_check")
        candidates = [cls.evaluate(check, key, estimator, threshold, prior) for threshold in (.05, .1, .2, .3, .5)]
        eligible = [item for item in candidates if item["candidate"]["fpr"] is not None and item["candidate"]["fpr"] <= .25]
        chosen = max(eligible, key=lambda item: (item["candidate"]["f2"] or 0, item["threshold"])) if eligible else candidates[-1]
        c, b = chosen["candidate"], chosen["current"]
        enough = len(labels) >= 100 and sum(labels) >= 5 and c["n"] >= 50 and c["positives"] >= 3
        gate = bool(enough and eligible and c["brier"] <= b["brier"] and c["brier"] <= c["constant_brier"])
        result = {"point_model": key, "fit_windows": len(labels), "fit_positives": sum(labels), "fit_prior": prior,
                  "calibration_check": chosen, "threshold_trials": candidates,
                  "validation_probability_gate": gate, "calibrated": False,
                  "reason": "Локальная ретроспектива, новый контроль отсутствует; поддержка и gate раскрыты явно."}
        # Порог сохранён до чтения результатов более поздних периодов.
        (output / "probability-selection-frozen.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        for name in ("retrospective_development", "retrospective_other_companies"):
            result[name] = cls.evaluate(read(name), key, estimator, chosen["threshold"], prior)
        np.savez(output / "residual-paths.npz", paths=estimator.paths)
        (output / "probabilities.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = ProbabilityStudy.run(args.output)
    print(json.dumps({k: result[k] for k in ("point_model", "fit_windows", "fit_positives", "validation_probability_gate")}, ensure_ascii=False))
