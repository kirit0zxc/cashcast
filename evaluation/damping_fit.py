"""Подбор и проверка затухания2.2 на контрольных окнах B4 (срезы 30.04–31.08.2026).

fit: прогоняет2.1, раскладывает её p50 на остаток, нерегулярный дрейф, регулярности и известные платежи,
подбирает α (дрейф) и β (регулярности) расширяющимся окном: срез k оценивается коэффициентами только
по срезам до k. Итоговые коэффициенты — по validation 30.04–31.07, затем настоящий прогон2.2 с ними.
check: тот же прогон2.2 с коэффициентами из кода, без подмены. Сентябрь уже просматривался в v2,
поэтому вывод ретроспективный. В отчёт идут только агрегаты, без строк выписок.

Запуск из корня репозитория: python -m evaluation.damping_fit --zip <датасет> --output <папка> --mode fit
"""

import argparse
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from evaluation.backtest import HOLDOUT, VALIDATION, fold, load_dataset, temporal_view  # noqa: E402

from app.modules.forecasting.service import get_forecast_service  # noqa: E402
from app.modules.forecasting.v2 import damped  # noqa: E402

CURRENT = "seasonal-estimated-2.1-w84"
CUTOFFS = (*VALIDATION, HOLDOUT)
BUCKETS = tuple(damped.DAMPING)
GRID = [round(0.1 * step, 1) for step in range(11)]
SEED, REPS = 42, 2000


def windows(path, log, smoke=0):
    """Окна как у контрольных срезов v2: validation не видит строк после 31.08."""
    transactions, balances = load_dataset(path)
    view_txns, view_balances = temporal_view(transactions, balances, HOLDOUT)
    rows = []
    # smoke — только проверка кода на слабой машине, числа не являются результатом.
    for company in sorted(transactions)[:smoke or None]:
        for cutoff in CUTOFFS:
            source = ((transactions[company], balances[company]) if cutoff == HOLDOUT
                      else (view_txns[company], view_balances[company]))
            entry, _reason = fold(company, *source, cutoff)
            if entry is not None:
                data, truth, cohort = entry
                rows.append({"company": company, "as_of": cutoff, "cohort": cohort, "data": data,
                             "opening": float(data.opening_balance_minor),
                             "actual": np.array([balance for _, _, balance in truth], dtype=float)})
    log(f"Окон: {len(rows)}")
    return rows


def run_model(rows, version, log):
    service = get_forecast_service(version)
    for number, row in enumerate(rows, 1):
        result = service.run(row["data"])
        if result.model_version != version:
            raise RuntimeError("Реестр вернул другую версию")
        recurring = defaultdict(int)
        for item in result.details["explanations"]:
            if item["kind"] == "recurrence":
                sign = 1 if item["detail"]["direction"] == "in" else -1
                recurring[item["detail"]["date"]] += sign * item["amount_minor"]
        known = np.cumsum([c["known_in_minor"] - c["known_out_minor"] for c in result.details["daily_components"]])
        row[version] = {
            "p10": np.array([p.balance_p10_minor for p in result.points], dtype=float),
            "p50": np.array([p.balance_p50_minor for p in result.points], dtype=float),
            "p90": np.array([p.balance_p90_minor for p in result.points], dtype=float),
            "known": known.astype(float),
            "regular": np.cumsum([recurring[p.point_date.isoformat()] for p in result.points]).astype(float),
            "reliable": result.details["paths"] > 0,
            "risk": result.risk.probability_any_negative,
        }
        if number % 100 == 0:
            log(f"{version}: {number}/{len(rows)}")


def offline(rows, table, unreliable):
    """Формула2.2 по компонентам2.1: остаток + α·дрейф + β·регулярности + известные платежи."""
    out = []
    for row in rows:
        c = row[CURRENT]
        drift = c["p50"] - row["opening"] - c["known"]
        alpha = np.ones(30)
        beta = np.ones(30)
        for (first, last), (a, b) in table.items():
            alpha[first - 1:last], beta[first - 1:last] = (a if c["reliable"] else unreliable), b
        out.append(row["opening"] + alpha * drift + beta * c["regular"] + c["known"] - c["regular"])
    return np.array(out)


def fit(rows):
    """Сетка 0..1 шагом 0,1: сначала α, β по надёжным окнам, затем α ненадёжных при найденных β."""
    reliable = [row for row in rows if row[CURRENT]["reliable"]]
    shaky = [row for row in rows if not row[CURRENT]["reliable"]]
    table = {}
    for first, last in BUCKETS:
        cols = slice(first - 1, last)
        best = None
        for a in GRID:
            for b in GRID:
                pred = offline(reliable, {(first, last): (a, b)}, 1.0)[:, cols] if reliable else None
                error = np.abs(pred - np.array([r["actual"][cols] for r in reliable])).mean() if reliable else 0
                if best is None or error < best[0] - 1e-9:
                    best = (error, a, b)
        table[(first, last)] = (best[1], best[2])
    errors = [np.abs(offline(shaky, table, a) - np.array([r["actual"] for r in shaky])).mean() if shaky else 0
              for a in GRID]
    return table, GRID[int(np.argmin(errors))]


def paired(rows, pred_a, pred_b):
    """Разность MAE в рублях (a − b), парный bootstrap по компаниям."""
    order = sorted({row["company"] for row in rows})
    group = np.searchsorted(order, [row["company"] for row in rows])
    actual = np.array([row["actual"] for row in rows])
    a = np.bincount(group, weights=np.abs(pred_a - actual).sum(axis=1), minlength=len(order))
    b = np.bincount(group, weights=np.abs(pred_b - actual).sum(axis=1), minlength=len(order))
    n = np.bincount(group, minlength=len(order)) * 30
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(REPS):
        w = np.bincount(rng.integers(0, len(order), len(order)), minlength=len(order))
        draws.append((w @ a - w @ b) / (w @ n) / 100)
    return {"estimate": float((a.sum() - b.sum()) / n.sum() / 100),
            "ci95": [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))],
            "companies_better": int((a < b).sum()), "companies": len(order)}


def auc(labels, scores):
    labels, scores = np.asarray(labels, dtype=float), np.asarray(scores, dtype=float)
    positives, negatives = labels.sum(), len(labels) - labels.sum()
    if not positives or not negatives:
        return None
    unique, inverse = np.unique(scores, return_inverse=True)
    pos = np.bincount(inverse, weights=labels, minlength=len(unique))
    neg = np.bincount(inverse, minlength=len(unique)) - pos
    return float((pos * (np.cumsum(neg) - neg + 0.5 * neg)).sum() / (positives * negatives))


def metrics(rows, preds):
    actual = np.array([row["actual"] for row in rows])
    result = {}
    for name, pred in preds.items():
        err = np.abs(pred - actual) / 100
        result[name] = {"mae_rub": float(err.mean()), "rmse_rub": float(np.sqrt((((pred - actual) / 100) ** 2).mean())),
                        "mae_by_bucket_rub": {f"{a}-{b}": float(err[:, a - 1:b].mean()) for a, b in BUCKETS},
                        "mae_by_h_rub": [float(v) for v in err.mean(axis=0)]}
    return result


def product_block(rows, versions):
    """Интервал и риск: только у продуктовых версий, на общей выборке окон."""
    actual = np.array([row["actual"] for row in rows])
    label = np.array([(row["actual"] < 0).any() for row in rows])
    new_gap = np.array([row["opening"] >= 0 for row in rows])
    both = np.array([all(row[v]["risk"] is not None for v in versions) for row in rows])
    out = {"risk_windows": int(both.sum()), "risk_events": int(label[both].sum()),
           "new_gap_windows": int((both & new_gap).sum()), "new_gap_events": int(label[both & new_gap].sum())}
    for version in versions:
        p10 = np.array([row[version]["p10"] for row in rows])
        p90 = np.array([row[version]["p90"] for row in rows])
        banded = (p90 > p10).any(axis=1)
        risk = np.array([row[version]["risk"] if row[version]["risk"] is not None else np.nan for row in rows])
        out[version] = {
            "coverage_p10_p90": float(((actual >= p10) & (actual <= p90))[banded].mean()) if banded.any() else None,
            "interval_width_rub": float(((p90 - p10)[banded] / 100).mean()) if banded.any() else None,
            "brier_any_negative": float(((risk[both] - label[both]) ** 2).mean()) if both.any() else None,
            "auc_any_negative": auc(label[both], risk[both]),
            "brier_new_gap": float(((risk[both & new_gap] - label[both & new_gap]) ** 2).mean())
            if (both & new_gap).any() else None,
            "auc_new_gap": auc(label[both & new_gap], risk[both & new_gap]),
        }
    return out


def clean(value):
    if isinstance(value, dict):
        return {(f"{k[0]}-{k[1]}" if isinstance(k, tuple) else str(k)): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fit", "check"), required=True)
    parser.add_argument("--smoke", type=int, default=0, help="Число первых компаний для проверки кода; не результат")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    start = time.time()

    def log(message):
        print(f"[{time.time() - start:7.1f}s] {message}", flush=True)

    rows = windows(args.zip, log, args.smoke)
    run_model(rows, CURRENT, log)
    summary = {"mode": args.mode, "smoke": args.smoke, "windows": len(rows),
               "code_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
                   "evaluation/damping_fit.py", "backend/app/modules/forecasting/v2/damped.py",
                   "backend/app/modules/forecasting/v2/service.py", "backend/app/modules/forecasting/service.py")}}
    if args.mode == "fit":
        folds, pooled_rows, pooled_pred = {}, [], []
        for k in range(1, len(CUTOFFS)):
            past = [row for row in rows if row["as_of"] in CUTOFFS[:k]]
            test = [row for row in rows if row["as_of"] == CUTOFFS[k]]
            table, unreliable = fit(past)
            folds[CUTOFFS[k].isoformat()] = {"damping": table, "unreliable_drift": unreliable}
            pooled_rows += test
            pooled_pred.append(offline(test, table, unreliable))
        pooled_pred = np.vstack(pooled_pred)
        cur = np.array([row[CURRENT]["p50"] for row in pooled_rows])
        pers = np.array([[row["opening"]] * 30 for row in pooled_rows])
        sept = np.array([row["as_of"] == HOLDOUT for row in pooled_rows])
        summary["rolling"] = {
            "folds": folds,
            "may_sep": metrics(pooled_rows, {"2.2 (подбор по прошлым срезам)": pooled_pred, "2.1": cur,
                                             "persistence": pers}),
            "may_sep_vs_2_1": paired(pooled_rows, pooled_pred, cur),
            "may_sep_vs_persistence": paired(pooled_rows, pooled_pred, pers),
            "sept_vs_2_1": paired([r for r, s in zip(pooled_rows, sept, strict=True) if s],
                                  pooled_pred[sept], cur[sept]),
            "sept_vs_persistence": paired([r for r, s in zip(pooled_rows, sept, strict=True) if s],
                                          pooled_pred[sept], pers[sept]),
        }
        # Итог — коэффициенты по validation: это последний фолд, который предсказывал сентябрь.
        damped.DAMPING, damped.UNRELIABLE_DRIFT = fit([row for row in rows if row["as_of"] in VALIDATION])
        log(f"Итоговые коэффициенты: {damped.DAMPING}, ненадёжные: {damped.UNRELIABLE_DRIFT}")
    summary["coefficients"] = {"damping": dict(damped.DAMPING), "unreliable_drift": damped.UNRELIABLE_DRIFT}
    run_model(rows, damped.MODEL_VERSION, log)
    formula = offline(rows, damped.DAMPING, damped.UNRELIABLE_DRIFT)
    real = np.array([row[damped.MODEL_VERSION]["p50"] for row in rows])
    summary["implementation_vs_formula_max_abs_kopecks"] = float(np.abs(real - formula).max())
    for scope, keep in (("validation_in_sample", lambda r: r["as_of"] != HOLDOUT),
                        ("september", lambda r: r["as_of"] == HOLDOUT)):
        part = [row for row in rows if keep(row)]
        preds = {"2.2": np.array([r[damped.MODEL_VERSION]["p50"] for r in part]),
                 "2.1": np.array([r[CURRENT]["p50"] for r in part]),
                 "persistence": np.array([[r["opening"]] * 30 for r in part])}
        summary[scope] = {"windows": len(part), "mae": metrics(part, preds),
                          "vs_2_1": paired(part, preds["2.2"], preds["2.1"]),
                          "vs_persistence": paired(part, preds["2.2"], preds["persistence"]),
                          "product": product_block(part, (CURRENT, damped.MODEL_VERSION))}
    summary["runtime_seconds"] = round(time.time() - start)
    (args.output / f"damping_{args.mode}.json").write_text(
        json.dumps(clean(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for scope in ("validation_in_sample", "september"):
        mae = summary[scope]["mae"]
        log(f"{scope}: MAE 2.2 {mae['2.2']['mae_rub']:.0f} · 2.1 {mae['2.1']['mae_rub']:.0f} · "
            f"persistence {mae['persistence']['mae_rub']:.0f}")
    log(f"Реализация против формулы: {summary['implementation_vs_formula_max_abs_kopecks']} коп.")


if __name__ == "__main__":
    main()
