"""Фиксированный point-selection B5; не читает даты после границы фазы."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
import tracemalloc
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from evaluation.backtest import EXPECTED_SHA256, Metrics, fold, load_dataset, temporal_view  # noqa: E402

from app.modules.forecasting.legacy_v1.baseline import BaselineForecastService  # noqa: E402
from app.modules.forecasting.legacy_v1.seasonal import SeasonalForecastService  # noqa: E402
from app.modules.forecasting.v2.engine import ExperimentalForecastService  # noqa: E402

CUTOFFS = (date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31))
PHASE_END = date(2026, 4, 30)


def company_split(company: str) -> str:
    return "heldout_company" if hashlib.sha256(company.encode()).digest()[0] % 5 == 0 else "development"


def fingerprints():
    paths = [
        Path(__file__),
        ROOT / "evaluation/backtest.py",
        ROOT / "evaluation/EXPERIMENT-B5-B6.md",
        ROOT / "backend/app/modules/contracts.py",
        *sorted((ROOT / "backend/app/modules/forecasting/legacy_v1").glob("*.py")),
        ROOT / "backend/app/modules/forecasting/seasonal.py",
        ROOT / "backend/app/modules/forecasting/scenarios.py",
        ROOT / "backend/app/modules/forecasting/v2/engine.py",
        ROOT / "backend/app/modules/forecasting/v2/quality.py",
        *sorted((ROOT / "backend/app/modules/categorization").rglob("*.py")),
        *sorted((ROOT / "backend/app/modules/planning").rglob("*.py")),
    ]
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in paths
        if path.name != "snapshot.py"
    }


def services():
    return {
        "baseline": BaselineForecastService(),
        "legacy_w84": SeasonalForecastService(),
        **{method: ExperimentalForecastService(method) for method in ("ewm", "winsor", "trend")},
    }


def choose(reports: dict, cutoff_reports: dict, timings: dict) -> dict:
    """Заранее заданный acceptance gate; тестовые периоды не участвуют."""
    legacy_mae = reports["legacy_w84"]["balance_mae_minor"]
    eligible = []
    gates = {}
    for method in ("ewm", "winsor", "trend"):
        gain = 1 - reports[method]["balance_mae_minor"] / legacy_mae if legacy_mae else 0
        worsening = sum(
            cutoff_reports[cutoff][method]["balance_mae_minor"]
            > 1.1 * cutoff_reports[cutoff]["legacy_w84"]["balance_mae_minor"]
            for cutoff in cutoff_reports
        )
        runtime_ratio = sum(timings[method]) / sum(timings["legacy_w84"])
        accepted = gain >= 0.05 and worsening < 2 and runtime_ratio <= 3
        gates[method] = {
            "mae_gain": gain,
            "worsening_cutoffs_over_10pct": worsening,
            "runtime_ratio": runtime_ratio,
            "accepted": accepted,
        }
        if accepted:
            eligible.append(method)
    # Baseline также остаётся ориентиром: если он лучше всех, новая версия не нужна.
    candidates = ["baseline", "legacy_w84", *eligible]
    selected = min(candidates, key=lambda name: reports[name]["balance_mae_minor"])
    return {"method": selected, "gates": gates, "rule": "EXPERIMENT-B5-B6.md; fixed before evaluation"}


def run(path: Path):
    started = time.perf_counter()
    transactions, balances = load_dataset(path)
    transactions, balances = temporal_view(transactions, balances, PHASE_END)
    models = services()
    metrics = {name: Metrics() for name in models}
    cutoff_metrics = {day.isoformat(): {name: Metrics() for name in models} for day in CUTOFFS}
    company_errors, timings = defaultdict(lambda: defaultdict(list)), defaultdict(list)
    skipped, cohorts = Counter(), Counter()
    profile_input = None
    versions = {}
    for company in sorted(transactions):
        if company_split(company) != "development":
            continue
        for as_of in CUTOFFS:
            item, reason = fold(company, transactions[company], balances[company], as_of)
            if item is None:
                skipped[reason] += 1
                continue
            data, truth, cohort = item
            cohorts[cohort] += 1
            if profile_input is None or len(data.txns) > len(profile_input.txns):
                profile_input = data
            for name, model in models.items():
                before = time.perf_counter()
                result = model.run(data)
                versions[name] = result.model_version
                timings[name].append(time.perf_counter() - before)
                metrics[name].add(result, truth, cohort)
                cutoff_metrics[as_of.isoformat()][name].add(result, truth, cohort)
                company_errors[name][company].append(
                    statistics.mean(
                        abs(point.balance_p50_minor - target[2])
                        for point, target in zip(result.points, truth, strict=True)
                    )
                )
    reports = {name: metric.report() for name, metric in metrics.items()}
    cutoff_reports = {
        day: {name: metric.report() for name, metric in values.items()} for day, values in cutoff_metrics.items()
    }
    if not all(reports[name]["folds"] for name in models):
        raise ValueError("Нет общей selection выборки")
    profiles = {}
    for name, model in models.items():
        profiles[name] = {}
        for horizon in (1, 7, 30, 90, 180):
            data = replace(profile_input, horizon_days=horizon)
            tracemalloc.start()
            before = time.perf_counter()
            result = model.run(data)
            elapsed = time.perf_counter() - before
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            profiles[name][str(horizon)] = {
                "seconds_with_tracemalloc": elapsed,
                "peak_python_bytes": peak,
                "points": len(result.points),
                "transactions": len(data.txns),
            }
    return {
        "experiment": "B5-selection-v2",
        "dataset_sha256": EXPECTED_SHA256,
        "phase_end": PHASE_END.isoformat(),
        "cutoffs": [day.isoformat() for day in CUTOFFS],
        "split": "sha256(company_id).digest()[0] %5 !=0 development; heldout excluded",
        "source_sha256": fingerprints(),
        "selection": choose(reports, cutoff_reports, timings),
        "models": versions,
        "reports": reports,
        "by_cutoff": cutoff_reports,
        "skipped": dict(skipped),
        "cohorts": dict(cohorts),
        "company_macro": {
            name: {
                "companies": len(values),
                "mean_mae_minor": statistics.mean(statistics.mean(errors) for errors in values.values()),
                "median_mae_minor": statistics.median(statistics.mean(errors) for errors in values.values()),
            }
            for name, values in company_errors.items()
        },
        "timing_without_tracemalloc": {
            name: {
                "total_seconds": sum(values),
                "median_seconds": statistics.median(values),
                "max_seconds": max(values),
            }
            for name, values in timings.items()
        },
        "profiles": profiles,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Синтетические данные; не банковская гарантия.",
            "Отсутствие строки условно нулевой день; полнота не доказана.",
            "Риск raw исследовательский, не калиброван этой point-selection оценкой.",
            "Peak memory только Python allocator одного расчёта, не RSS всего процесса.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.zip)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "selection": report["selection"],
                "folds": report["reports"]["legacy_w84"]["folds"],
                "elapsed_seconds": report["elapsed_seconds"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
