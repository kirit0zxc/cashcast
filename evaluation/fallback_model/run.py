"""Локальный эксперимент; разделение выбора и последующего отчёта заморожено."""

import argparse
import hashlib
import json
import platform
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.forecasting.service import get_forecast_service
from .data import Dataset
from .features import DirectCandidate
from .metrics import Score


class Experiment:
    def __init__(self, source, output):
        self.dataset = Dataset(source)
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.models = {}
        self.timings = defaultdict(list)
        self.report = {"base_commit": "a92bd5013b5b5d7e5008157815160b67fd762edf",
                       "new_control_dataset_seen": False, "production_activated": False,
                       "probability_calibrated": False, "python": platform.python_version(),
                       "numpy": np.__version__, "seed": 20261024,
                       "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "limitations": ["Ретроспективные периоды уже изучались прежде; это не нетронутый test.",
                                       "Данные организаторов синтетические; метрики не гарантируют качество МСП.",
                                       "Классификация нового минуса отличается от качества категоризации."]}

    def save(self):
        (self.output / "results.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")

    def train(self):
        started = time.perf_counter()
        x, y, weights, summary = self.dataset.training()
        self.report["training"] = summary
        print(f"Prepared {summary['rows']} rows / {summary['windows']} windows / {summary['companies']} companies", flush=True)
        for depth in (4, 6):
            name = f"direct_depth{depth}"
            before = time.perf_counter()
            candidate = DirectCandidate(depth).fit(x, y, weights)
            self.models[name] = candidate
            candidate.model.save_model(str(self.output / f"{name}.cbm"))
            self.report.setdefault("fit_seconds", {})[name] = time.perf_counter() - before
            print(f"Trained {name} in {self.report['fit_seconds'][name]:.1f}s", flush=True)
            self.save()
        self.report["train_total_seconds"] = time.perf_counter() - started

    def evaluate(self, cutoffs, limit, heldout=False):
        windows, excluded = self.dataset.windows(cutoffs, limit, heldout)
        rows = []
        service = get_forecast_service()
        baseline = get_forecast_service("baseline-repeat-week-0.1")
        for index, (data, truth, cohort) in enumerate(windows):
            row = {"company": data.account_id, "cutoff": data.as_of.isoformat(),
                   "opening": data.opening_balance_minor, "truth": truth, "cohort": cohort,
                   "models": {}, "fallback": {}}
            for name, method in (("current", service), ("baseline7", baseline)):
                before = time.perf_counter()
                result = method.run(data)
                self.timings[name].append(time.perf_counter() - before)
                row["models"][name] = np.array([[p.inflow_minor, p.outflow_minor, p.balance_p50_minor] for p in result.points])
                if name == "current":
                    row["current_probability"] = result.risk.probability_any_negative
                    row["current_daily_probability"] = [p.probability_negative for p in result.points]
            for name, candidate in self.models.items():
                before = time.perf_counter()
                flows, balance, scale, quality = candidate.predict(data)
                # Слабая история не исключается из сравнения: используем явный fallback.
                fallback = quality.history_days < 28
                predicted = row["models"]["current"].copy() if fallback else np.column_stack([flows, balance])
                self.timings[name].append(time.perf_counter() - before)
                row["models"][name] = predicted
                row["fallback"][name] = fallback
                row["scale"] = scale
                for weight in (0.25, 0.5, 0.75):
                    mixed_name = f"{name}_blend{weight}"
                    # Потоки — ожидаемые суммы; кривая p50 — смесь точечных прогнозов.
                    # Медиана остатка не обязана совпадать с суммой математических ожиданий.
                    row["models"][mixed_name] = np.rint(weight * predicted + (1 - weight) * row["models"]["current"]).astype(np.int64)
            rows.append(row)
            if (index + 1) % 100 == 0:
                print(f"Evaluated {index + 1}/{len(windows)} windows; heldout={heldout}", flush=True)
        return rows, excluded

    @staticmethod
    def summarize(rows):
        if not rows:
            return {}
        return {key: {str(h): Score.summarize(rows, key, h) for h in (7, 14, 30)} for key in rows[0]["models"]}

    def select(self, validation):
        summary = self.summarize(validation)
        baseline = summary["current"]["30"]
        keys = [key for key in summary if key not in {"current", "baseline7"}]
        best = min(keys, key=lambda key: summary[key]["30"]["mae_rub"])
        challenger = summary[best]["30"]
        improvements = 1 - challenger["mae_rub"] / baseline["mae_rub"]
        worsened = sum(value > 1.1 * baseline["cutoff_mae_rub"][cutoff]
                       for cutoff, value in challenger["cutoff_mae_rub"].items())
        allowed = improvements >= 0.05 and worsened < 2
        decision = {"selected": best if allowed else "current", "challenger": best,
                    "validation_mae_improvement": improvements, "cutoffs_worse_over_10pct": worsened,
                    "point_validation_gate": allowed, "selection_source": "validation_only",
                    "refit_on_test": False}
        self.report["selection"] = decision
        self.report["validation"] = summary
        self.save()
        # Выбор закрепляется до просмотра следующего периода.
        (self.output / "selection-frozen.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
        print(f"Frozen selection: {decision}", flush=True)
        return decision

    def run(self):
        from catboost import __version__ as catboost_version
        self.report["catboost"] = catboost_version
        self.train()
        validation, excluded = self.evaluate([date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)], date(2026, 4, 30))
        self.report["validation_excluded"] = excluded
        selection = self.select(validation)
        # Все последующие результаты описываются; они не меняют выбор модели.
        for name, cutoffs, limit, heldout in [
            ("calibration", [date(2026, 4, 30), date(2026, 5, 31)], date(2026, 6, 30), False),
            ("calibration_check", [date(2026, 6, 30)], date(2026, 7, 30), False),
            ("retrospective_development", [date(2026, 7, 31), date(2026, 8, 31)], date(2026, 9, 30), False),
            ("retrospective_other_companies", [date(2026, 7, 31), date(2026, 8, 31)], date(2026, 9, 30), True),
        ]:
            rows, rejected = self.evaluate(cutoffs, limit, heldout)
            self.report[name] = {"scores": self.summarize(rows), "excluded": rejected,
                                 "paired_challenger_vs_current": Score.paired_interval(rows, selection["challenger"])}
            # Локальные численные окна для проверки вероятностей, без назначений платежей.
            # Файлы лежат в data/raw и никогда не предназначены для публикации.
            import pickle
            with (self.output / f"{name}.pickle").open("wb") as stream:
                pickle.dump(rows, stream)
            self.save()
            print(f"Finished {name}: {len(rows)} windows", flush=True)
        self.report["inference_median_seconds"] = {key: float(np.median(values)) for key, values in self.timings.items()}
        self.report["weights_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.glob("*.cbm")}
        self.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    Experiment(args.zip, args.output).run()


if __name__ == "__main__":
    main()
