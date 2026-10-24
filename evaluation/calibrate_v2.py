"""B6: fit/check/test по пререгистрации, конечный gate до ретроспективного test."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import tracemalloc
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from evaluation.backtest import EXPECTED_SHA256, Metrics, fold, load_dataset, temporal_view  # noqa: E402
from evaluation.risk_v2 import choose_threshold, paired_company_bootstrap, report  # noqa: E402
from evaluation.select_v2 import company_split, fingerprints, services  # noqa: E402

from app.modules.forecasting.v2.calibration import fit_calibrators  # noqa: E402
from app.modules.forecasting.v2.quality import assess_quality  # noqa: E402
from app.modules.forecasting.v2.service import GuardedForecastService  # noqa: E402

PHASES = {
    "fit": ((date(2026, 4, 30), date(2026, 5, 31)), date(2026, 6, 30)),
    "check": ((date(2026, 6, 30),), date(2026, 7, 31)),
    "retrospective_test": ((date(2026, 7, 31), date(2026, 8, 31)), date(2026, 9, 30)),
}


def collect(transactions, balances, phase, model):
    cutoffs, end = PHASES[phase]
    transactions, balances = temporal_view(transactions, balances, end)
    records, excluded = [], Counter()
    for company in sorted(transactions):
        split = company_split(company)
        if phase == "fit" and split != "development":
            continue
        for as_of in cutoffs:
            item, reason = fold(company, transactions[company], balances[company], as_of)
            if item is None:
                excluded[f"{split}:{reason}"] += 1
                continue
            data, truth, cohort = item
            quality = assess_quality(data)
            if not quality.eligible_for_probability:
                excluded[f"{split}:quality_probability_unavailable"] += 1
                continue
            result = model.run(data)
            if result.risk.probability_any_negative is None or any(
                point.probability_negative is None for point in result.points
            ):
                excluded[f"{split}:model_probability_unavailable"] += 1
                continue
            actual = [balance < 0 for _, _, balance in truth]
            records.append(
                {
                    "company": company,
                    "key": as_of.isoformat(),
                    "split": split,
                    "cohort": cohort,
                    "opening_negative": data.opening_balance_minor < 0,
                    "horizon_raw": result.risk.probability_any_negative,
                    "daily_raw": [point.probability_negative for point in result.points],
                    "daily_actual": actual,
                    "horizon_actual": any(actual),
                    "lead_days": actual.index(True) + 1 if any(actual) and data.opening_balance_minor >= 0 else None,
                }
            )
    return records, dict(excluded)


def observations(records, channel):
    if channel == "horizon":
        return [(row["horizon_raw"], row["horizon_actual"]) for row in records]
    return [
        (probability, actual)
        for row in records
        for probability, actual in zip(row["daily_raw"], row["daily_actual"], strict=True)
    ]


def transform(records, horizon_model, daily_model, *, enforce_union=True):
    horizon, daily = [], []
    adjusted_union = 0
    for record in records:
        probabilities = [daily_model.predict(value) for value in record["daily_raw"]]
        mapped = horizon_model.predict(record["horizon_raw"])
        final = max(mapped, max(probabilities)) if enforce_union else mapped
        adjusted_union += final > mapped
        horizon.append(
            {
                "company": record["company"],
                "key": record["key"],
                "probability": final,
                "actual": record["horizon_actual"],
                "lead_days": record["lead_days"],
            }
        )
        daily.extend(
            {
                "company": record["company"],
                "key": f"{record['key']}:{index}",
                "probability": probability,
                "actual": actual,
            }
            for index, (probability, actual) in enumerate(zip(probabilities, record["daily_actual"], strict=True))
        )
    return {"horizon": horizon, "daily": daily, "union_adjusted_folds": adjusted_union}


def support(fit, check, channel):
    fit_min, fit_pos, check_min, check_pos = (100, 5, 50, 3) if channel == "horizon" else (1000, 10, 500, 5)
    f, c = observations(fit, channel), observations(check, channel)
    return {
        "fit_count": len(f),
        "fit_positives": sum(value for _, value in f),
        "check_count": len(c),
        "check_positives": sum(value for _, value in c),
        "required": [fit_min, fit_pos, check_min, check_pos],
        "passed": len(f) >= fit_min
        and sum(value for _, value in f) >= fit_pos
        and len(c) >= check_min
        and sum(value for _, value in c) >= check_pos,
    }


def select_configuration(fit, check, fitted):
    development = [row for row in check if row["split"] == "development"]
    candidates = {}
    chosen = {}
    # Выбор каждого канала отдельно, потом проверка union без подбора новой пары.
    for channel in ("horizon", "daily"):
        values = observations(development, channel)
        candidates[channel] = {
            name: mean((model.predict(probability) - actual) ** 2 for probability, actual in values) if values else None
            for name, model in fitted[channel].items()
        }
        chosen[channel] = min(fitted[channel], key=lambda name: candidates[channel][name] if values else float("inf"))
    gated = transform(development, fitted["horizon"][chosen["horizon"]], fitted["daily"][chosen["daily"]])
    supports = {channel: support(fit, development, channel) for channel in ("horizon", "daily")}
    comparisons, reasons = {}, []
    for split in ("development", "heldout_company"):
        records = [row for row in check if row["split"] == split]
        selected = transform(records, fitted["horizon"][chosen["horizon"]], fitted["daily"][chosen["daily"]])
        raw = transform(records, fitted["horizon"]["raw"], fitted["daily"]["raw"])
        constant = transform(records, fitted["horizon"]["constant"], fitted["daily"]["constant"])
        comparisons[split] = {}
        for channel in ("horizon", "daily"):
            selected_brier = report(selected[channel])["brier"]
            raw_brier, constant_brier = report(raw[channel])["brier"], report(constant[channel])["brier"]
            passed = selected_brier is not None and selected_brier <= min(raw_brier, constant_brier) + 1e-15
            comparisons[split][channel] = {
                "selected_brier": selected_brier,
                "raw_brier": raw_brier,
                "constant_brier": constant_brier,
                "passed": passed,
                "versus_raw": paired_company_bootstrap(selected[channel], raw[channel]),
                "versus_constant": paired_company_bootstrap(selected[channel], constant[channel]),
            }
            if not passed:
                reasons.append(f"{split}:{channel}:brier_quality_not_verified")
    for channel, values in supports.items():
        if not values["passed"]:
            reasons.append(f"{channel}:insufficient_calibration_support")
    return {
        "chosen": chosen,
        "candidate_check_brier_before_union": candidates,
        "support": supports,
        "check_after_union": comparisons,
        "probability_verified": not reasons,
        "fallback_reasons": reasons,
        "union_adjusted_development_folds": gated["union_adjusted_folds"],
        "threshold": choose_threshold(gated["horizon"]),
        "fit_models": {
            channel: {name: model.to_dict() for name, model in models.items()} for channel, models in fitted.items()
        },
    }


def phase_report(records, fitted, config):
    output = {}
    threshold = config["threshold"]["selected"]
    threshold = threshold["threshold"] if threshold else None
    for split in ("development", "heldout_company"):
        subset = [row for row in records if row["split"] == split]
        alternatives = {
            name: transform(subset, fitted["horizon"][name], fitted["daily"][name]) for name in fitted["horizon"]
        }
        alternatives["selected_pair"] = transform(
            subset, fitted["horizon"][config["chosen"]["horizon"]], fitted["daily"][config["chosen"]["daily"]]
        )
        output[split] = {
            name: {
                "horizon": report(values["horizon"], threshold),
                "daily": report(values["daily"]),
                "union_adjusted_folds": values["union_adjusted_folds"],
            }
            for name, values in alternatives.items()
        }
        output[split]["selected_paired_ci"] = {
            channel: {
                "versus_raw": paired_company_bootstrap(
                    alternatives["selected_pair"][channel], alternatives["raw"][channel]
                ),
                "versus_constant": paired_company_bootstrap(
                    alternatives["selected_pair"][channel], alternatives["constant"][channel]
                ),
            }
            for channel in ("horizon", "daily")
        }
    return output


def starting_balance_audit(records, fitted, config):
    """Post hoc описательная проверка; не выбирает параметры/метод/порог."""
    output = {}
    threshold = config["threshold"]["selected"]
    threshold = threshold["threshold"] if threshold else None
    for split in ("development", "heldout_company"):
        output[split] = {}
        for negative in (False, True):
            subset = [row for row in records if row["split"] == split and row["opening_negative"] == negative]
            selected = transform(
                subset, fitted["horizon"][config["chosen"]["horizon"]], fitted["daily"][config["chosen"]["daily"]]
            )
            raw = transform(subset, fitted["horizon"]["raw"], fitted["daily"]["raw"])
            constant = transform(subset, fitted["horizon"]["constant"], fitted["daily"]["constant"])
            persistence = {
                channel: [{**row, "probability": float(negative)} for row in selected[channel]]
                for channel in ("horizon", "daily")
            }
            output[split]["already_negative" if negative else "nonnegative_opening"] = {
                name: {
                    channel: report(values[channel], threshold if channel == "horizon" else None)
                    for channel in ("horizon", "daily")
                }
                for name, values in {
                    "selected": selected,
                    "raw": raw,
                    "constant": constant,
                    "persistence": persistence,
                }.items()
            }
    return output


def product_audit(transactions, balances, model):
    """Описательная проверка окончательного fallback, без выбора новых параметров."""
    cutoffs, end = PHASES["retrospective_test"]
    transactions, balances = temporal_view(transactions, balances, end)
    guarded = GuardedForecastService()
    metrics = {name: Metrics() for name in ("guarded", "selected_point_reference")}
    modes, excluded, reasons = Counter(), Counter(), Counter()
    changed, profile_input, elapsed = 0, None, []
    for company in sorted(transactions):
        for as_of in cutoffs:
            item, reason = fold(company, transactions[company], balances[company], as_of)
            if item is None:
                excluded[reason] += 1
                continue
            data, truth, cohort = item
            before = time.perf_counter()
            result = guarded.run(data)
            elapsed.append(time.perf_counter() - before)
            reference = model.run(data)
            metrics["guarded"].add(result, truth, cohort)
            metrics["selected_point_reference"].add(reference, truth, cohort)
            changed += any(
                left.balance_p50_minor != right.balance_p50_minor
                for left, right in zip(result.points, reference.points, strict=True)
            )
            modes[result.details["quality"]["mode"]] += 1
            reasons.update(result.details["risk_probability"]["reasons"])
            if profile_input is None or len(data.txns) > len(profile_input.txns):
                profile_input = data
    profiles = {}
    for horizon in (1, 7, 30, 90, 180):
        tracemalloc.start()
        before = time.perf_counter()
        result = guarded.run(replace(profile_input, horizon_days=horizon))
        seconds = time.perf_counter() - before
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        profiles[str(horizon)] = {
            "seconds_with_tracemalloc": seconds,
            "peak_python_bytes": peak,
            "points": len(result.points),
            "transactions": len(profile_input.txns),
        }
    return {
        "model_version": guarded.model_version,
        "reports": {name: value.report() for name, value in metrics.items()},
        "changed_point_folds_after_quality_guard": changed,
        "quality_modes": dict(modes),
        "fallback_reasons": dict(reasons),
        "skipped": dict(excluded),
        "profiles": profiles,
        "median_seconds_without_tracemalloc": sorted(elapsed)[len(elapsed) // 2],
        "note": (
            "Point math retained; after reconciliation break ALL history is restricted. "
            "Probabilities withheld, not zero."
        ),
    }


def run(path, selection_path):
    started = time.perf_counter()
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection["experiment"] != "B5-selection-v2" or selection["dataset_sha256"] != EXPECTED_SHA256:
        raise ValueError("Неверная selection конфигурация")
    method = selection["selection"]["method"]
    if method == "baseline":
        raise ValueError("У baseline нет вероятностей; требуется явный None fallback")
    model = services()[method]
    transactions, balances = load_dataset(path)
    fit, fit_excluded = collect(transactions, balances, "fit", model)
    check, check_excluded = collect(transactions, balances, "check", model)
    fitted = {channel: fit_calibrators(observations(fit, channel)) for channel in ("horizon", "daily")}
    config = select_configuration(fit, check, fitted)
    # После этой строки config не изменяется: test может только раскрыть ограничение.
    config_sha256 = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    check_report = phase_report(check, fitted, config)
    test, test_excluded = collect(transactions, balances, "retrospective_test", model)
    test_report = phase_report(test, fitted, config)
    # Дополнительный аудит предложен после первого output с leadtime1.5дня. Старый
    # point-estimate gate не доказывает предсказание нового разрыва. Параметры не меняем;
    # тот же минимум событий требуем на неотрицательном opening перед продуктовой выдачей.
    new_gap_support = {
        channel: support(
            [row for row in fit if not row["opening_negative"]],
            [row for row in check if row["split"] == "development" and not row["opening_negative"]],
            channel,
        )
        for channel in ("horizon", "daily")
    }
    # Test вправе отвергнуть продуктовую вероятность, но не выбрать другую пару/порог.
    test_gate = {}
    for split, values in test_report.items():
        test_gate[split] = {}
        for channel in ("horizon", "daily"):
            selected_brier = values["selected_pair"][channel]["brier"]
            raw_brier, constant_brier = values["raw"][channel]["brier"], values["constant"][channel]["brier"]
            test_gate[split][channel] = (
                selected_brier is not None and selected_brier <= min(raw_brier, constant_brier) + 1e-15
            )
    source = fingerprints()
    for filename in (
        "evaluation/calibrate_v2.py",
        "evaluation/risk_v2.py",
        "backend/app/modules/forecasting/v2/calibration.py",
        "backend/app/modules/forecasting/v2/service.py",
        "backend/app/modules/forecasting/v2/legacy_limits.py",
        "backend/app/modules/forecasting/service.py",
    ):
        source[filename] = hashlib.sha256((ROOT / filename).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return {
        "experiment": "B6-risk-calibration-v2",
        "dataset_sha256": EXPECTED_SHA256,
        "selection_sha256": hashlib.sha256(selection_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "point_method": method,
        "product_fallback_audit": product_audit(transactions, balances, model),
        "source_sha256": source,
        "config": config,
        "config_sha256_before_test": config_sha256,
        "retrospective_rejection_gate": test_gate,
        "preregistered_point_estimate_gates_passed": config["probability_verified"]
        and all(value for group in test_gate.values() for value in group.values()),
        "posthoc_new_gap_support": new_gap_support,
        "deploy_probability_verified": config["probability_verified"]
        and all(value for group in test_gate.values() for value in group.values())
        and all(values["passed"] for values in new_gap_support.values()),
        "starting_balance_audit_posthoc": {
            "fit": starting_balance_audit(fit, fitted, config),
            "check": starting_balance_audit(check, fitted, config),
            "retrospective_test": starting_balance_audit(test, fitted, config),
        },
        "phases": {
            name: {"cutoffs": [day.isoformat() for day in values[0]], "phase_end": values[1].isoformat()}
            for name, values in PHASES.items()
        },
        "excluded": {"fit": fit_excluded, "check": check_excluded, "retrospective_test": test_excluded},
        "fit_folds": len(fit),
        "check": check_report,
        "retrospective_test": test_report,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Ретроспективный test частично просмотрен в B4; не новый нетронутый период.",
            "Синтетические компании; перенос на реальные банковские данные не доказан.",
            "Вероятности не подтверждены для horizon!=30, scenarios, explicit plans.",
            "Порог выбран только на check; FPR=FP/(FP+TN), None не заменяется нулём.",
            "CIs перевыбирают компании, а не зависимые дни внутри компании.",
            "Leadtime только при неотрицательном opening: уже существующий минус не является ранним предупреждением.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--selection", type=Path, default=ROOT / "evaluation/selection-v2.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.zip, args.selection)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "fit_folds": result["fit_folds"],
                "chosen": result["config"]["chosen"],
                "preregistered_point_estimate_gate": result["config"]["probability_verified"],
                "product_probability_verified": result["deploy_probability_verified"],
                "fallback": result["config"]["fallback_reasons"],
                "elapsed_seconds": result["elapsed_seconds"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
