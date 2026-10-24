"""Замороженный выбор риска по ранним срезам; поздние ответы не участвуют в настройке."""

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.forecasting.service import get_forecast_service
from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from evaluation.real_data.risk import metrics
from .model import ALPHAS, GapClassifier, ReserveFeatures, ReserveModel


class RiskExperiment:
    def __init__(self, source, output):
        self.data = Dataset(source)
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.reserves = {}
        self.classifier = None
        self.report = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "production_activated": False, "calibrated": False, "independent_control": False,
                       "protocol": "journal/02_liquidity_risk.md", "seed": 20261024}

    def save(self):
        (self.output / "results.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")

    def prepare(self, dates, limit, heldout=False):
        windows, excluded = self.data.windows(dates, limit, heldout)
        rows = []
        for snapshot, truth, cohort in windows:
            x, scale, quality, empirical = ReserveFeatures.make(snapshot)
            if quality.history_days < 28:
                excluded["short_history"] = excluded.get("short_history", 0) + 1
                continue
            reserve = ReserveFeatures.reserve(truth[:, :2])
            rows.append({"snapshot": snapshot, "truth": truth, "features": x, "scale": scale,
                         "quality": quality, "empirical": empirical, "reserve": reserve / scale,
                         "opening": snapshot.opening_balance_minor / scale,
                         "label": int(snapshot.opening_balance_minor < reserve), "cohort": cohort})
        return rows, excluded

    @staticmethod
    def weights(rows):
        counts = Counter(row["snapshot"].account_id for row in rows)
        return np.asarray([len(rows) / len(counts) / counts[row["snapshot"].account_id] for row in rows])

    def train(self):
        cutoffs, day = [], date(2024, 12, 31)
        while day+timedelta(days=30) <= date(2025, 12, 31):
            cutoffs.append(day)
            day += timedelta(days=14)
        rows, excluded = self.prepare(cutoffs, date(2025, 12, 31))
        x, y = np.array([row["features"] for row in rows]), np.array([row["reserve"] for row in rows])
        fit = [row for row in rows if row["opening"] >= 0]
        self.prior = (sum(row["label"] for row in fit) + .5) / (len(fit) + 1)
        self.report["train"] = {"reserve_windows": len(rows), "risk_windows": len(fit),
                                "positive_windows": sum(row["label"] for row in fit),
                                "positive_companies": len({row["snapshot"].account_id for row in fit if row["label"]}),
                                "companies": len({row["snapshot"].account_id for row in rows}), "excluded": excluded,
                                "constant_prior": self.prior}
        for depth in (4, 6):
            before = time.perf_counter()
            self.reserves[f"reserve{depth}"] = ReserveModel(depth).fit(x, y, self.weights(rows))
            self.reserves[f"reserve{depth}"].model.save_model(str(self.output / f"reserve{depth}.cbm"))
            print(f"Trained reserve{depth}: {time.perf_counter()-before:.1f}s", flush=True)
        self.classifier = GapClassifier().fit(np.array([row["features"] for row in fit]),
                                             [row["label"] for row in fit], self.weights(fit))
        self.classifier.model.save_model(str(self.output / "classifier.cbm"))
        print(f"Trained classifier on {len(fit)} windows with {self.report['train']['positive_windows']} positives", flush=True)
        self.save()

    def predict(self, rows):
        x = np.array([row["features"] for row in rows])
        quantiles = {name: model.predict_quantiles(x) for name, model in self.reserves.items()}
        classifier = self.classifier.predict(x)
        service = get_forecast_service()
        for index, row in enumerate(rows):
            current = service.run(row["snapshot"])
            row["scores"] = {"current": current.risk.probability_any_negative,
                             "classifier": float(classifier[index]), "constant": self.prior}
            empirical = row["empirical"]
            row["scores"]["historical_reserve"] = float((np.sum(empirical > row["opening"])+.5) / (len(empirical)+1)) if len(empirical) else None
            row["quantiles"] = {}
            for name, values in quantiles.items():
                row["quantiles"][name] = values[index]
                row["scores"][name] = ReserveModel.probability(values[index], row["opening"])
        return rows

    def statistics(self, rows, name, threshold):
        valid = [row for row in rows if row["opening"] >= 0 and row["scores"]["current"] is not None and row["scores"][name] is not None]
        y = [row["label"] for row in valid]
        p = [row["scores"][name] for row in valid]
        result = {**metrics(y, p, threshold, self.prior), **Score.classification(y, np.array(p) >= threshold),
                  "threshold": threshold, "evaluated_companies": len({row["snapshot"].account_id for row in valid}),
                  "excluded_from_common_risk": len(rows)-len(valid)}
        if name in self.reserves:
            values = np.array([row["quantiles"][name] for row in rows])
            truth = np.array([row["reserve"] for row in rows])
            scales = np.array([row["scale"] for row in rows]) / 100
            error = (values[:, 4] - truth) * scales
            result["reserve"] = {"pinball_normalized": ReserveModel.pinball(truth, values),
                                 "mae_rub": float(np.mean(abs(error))), "mse_rub2": float(np.mean(error**2)),
                                 "rmse_rub": float(np.sqrt(np.mean(error**2))),
                                 "coverage_q90": float(np.mean(truth <= values[:, 6]))}
        return result

    def choose(self, rows):
        comparisons = {}
        for name in ("current", "historical_reserve", "classifier", "reserve4", "reserve6"):
            trials = [self.statistics(rows, name, t) for t in (.01, .02, .05, .1, .2, .3, .5)]
            eligible = [item for item in trials if item["fpr"] is not None and item["fpr"] <= .1]
            if eligible:
                selected = max(eligible, key=lambda item: (item["f2"] or 0., item["threshold"]))
                selected["feasible_threshold"] = True
            else:
                selected = trials[-1]
                selected["feasible_threshold"] = False
            comparisons[name] = {"selected": selected, "trials": trials}
        reserve_name = min(self.reserves, key=lambda name: comparisons[name]["selected"]["reserve"]["pinball_normalized"])
        names = [name for name in (reserve_name, "classifier", "historical_reserve", "current") if comparisons[name]["selected"]["feasible_threshold"]]
        best = max(names, key=lambda name: (comparisons[name]["selected"]["f2"] or 0., comparisons[name]["selected"]["average_precision"] or 0., -comparisons[name]["selected"]["brier"])) if names else "current"
        decision = {"reserve_selected": reserve_name, "risk_selected": best,
                    "thresholds": {name: value["selected"]["threshold"] for name, value in comparisons.items()},
                    "based_on": "validation only; tiny positive support disclosed", "locked_before_later_predictions": True}
        self.report["validation"] = comparisons
        self.report["selection"] = decision
        (self.output / "selection-frozen.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
        self.save()
        print(f"Frozen risk selection: {decision}", flush=True)
        return decision

    def run(self):
        self.train()
        rows, excluded = self.prepare([date(2026,1,31),date(2026,2,28),date(2026,3,31)], date(2026,4,30))
        self.report["validation_excluded"] = excluded
        decision = self.choose(self.predict(rows))
        for name, dates, limit, heldout in [
            ("calibration",[date(2026,4,30),date(2026,5,31)],date(2026,6,30),False),
            ("check",[date(2026,6,30)],date(2026,7,30),False),
            ("retrospective_development",[date(2026,7,31),date(2026,8,31)],date(2026,9,30),False),
            ("retrospective_other_companies",[date(2026,7,31),date(2026,8,31)],date(2026,9,30),True),
        ]:
            rows, excluded = self.prepare(dates,limit,heldout)
            rows = self.predict(rows)
            report = {model:self.statistics(rows,model,threshold) for model,threshold in decision["thresholds"].items()}
            report["current_default"] = self.statistics(rows,"current",.5)
            self.report[name] = {"scores":report,"excluded":excluded}
            # Внутренние численные результаты, без текстов выписок, только локально.
            serial = [{"company":row["snapshot"].account_id,"cutoff":row["snapshot"].as_of.isoformat(),
                       "opening":row["opening"],"label":row["label"],"scores":row["scores"]} for row in rows]
            (self.output / f"{name}-rows.json").write_text(json.dumps(serial),encoding="utf-8")
            self.save()
            print(f"Finished {name}: {len(rows)} windows",flush=True)
        self.report["weights_sha256"] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.glob("*.cbm")}
        self.save()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--zip",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    RiskExperiment(args.zip,args.output).run()


if __name__ == "__main__":
    main()
