"""Сравнение текущей модели CashCast с кандидатами на датасете организаторов, протокол v2.

Запуск из корня репозитория (Colab или локально, Python 3.12+, lightgbm, scikit-learn, matplotlib):
    python -m evaluation.model_compare.run --zip cashflow_dataset_participants.zip --output out --export
"""

import argparse
import hashlib
import json
import platform
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import numpy as np

from . import artifacts, export, plots, scoring
from .models import (
    BASELINE,
    CURRENT,
    REFERENCE,
    GlobalLightGBM,
    ProductModel,
    RiskModels,
    ensemble,
    naive_prediction,
    persistence_prediction,
)
from .organizers import HOLDOUT, VALIDATION, build, load, train_for

CUR, REF, PERS = "Текущая 2.1-w84", "Эталон 1.0-w84 (B4)", "Persistence (остаток не меняется)"
LGBM, ENS, ENSP = "LightGBM v2", "Ансамбль 2.1 + LightGBM v2", "Ансамбль persistence + LightGBM v2"
BASE, NAIVE = "Baseline (повтор недели)", "Сезонный naive (месяц)"
REGRESSION = (BASE, NAIVE, REF, CUR, PERS, LGBM, ENS, ENSP)
CANDIDATES = (LGBM, ENS, ENSP)
REFERENCES = (CUR, REF, PERS)
RISK = (CUR, *RiskModels.NAMES)
RISK_TRAINED = RiskModels.NAMES[:3]
RISK_PERSISTENCE = RiskModels.NAMES[4]
NEW_GAP = (CUR, RiskModels.NAMES[1], *RiskModels.NEW_GAP)
# Опубликованные B4 числа эталона 1.0-w84: проверка, что стенд воспроизводит протокол.
B4 = {"validation": (517, 1575177.46), "holdout": (122, 1072364.48)}
ROOT = Path(__file__).resolve().parents[2]


def save_and_check(regressor, risk_models, rows, scores, folder):
    """Сохраняет веса среза и проверяет, что загруженные из файлов модели дают те же прогнозы."""
    artifacts.save(regressor, risk_models, folder)
    loaded, loaded_risk = artifacts.load(folder)
    kopecks = max((float(np.nanmax(np.abs(loaded.predict(w)[k] - p[LGBM][k])))
                   for w, p in rows for k in ("p10", "p50", "p90", "inc", "out")), default=0.0)
    reloaded = loaded_risk.predict([w for w, _ in rows]) if rows else {}
    probability = max((float(np.max(np.abs(reloaded[n] - scores[n]))) for n in reloaded), default=0.0)
    return {"reload_max_abs_diff_kopecks": kopecks, "reload_max_abs_diff_probability": probability}


def predict_cutoff(train, control, cutoff, smoke, log, export_dir=None):
    fit = train_for(train, cutoff)
    started = time.time()
    regressor = GlobalLightGBM().fit(fit, smoke)
    risk_models = RiskModels().fit(fit, smoke)
    log(f"{cutoff}: обучено на {len(fit)} окнах за {time.time() - started:.0f} c")
    products = {BASE: ProductModel(BASELINE), REF: ProductModel(REFERENCE), CUR: ProductModel(CURRENT)}
    rows, failures = [], Counter()
    for window in control.get(cutoff, []):
        try:
            predictions = {name: model.predict(window) for name, model in products.items()}
        except Exception as error:
            failures[type(error).__name__] += 1
            continue
        predictions[NAIVE] = naive_prediction(window)
        predictions[PERS] = persistence_prediction(window)
        predictions[LGBM] = regressor.predict(window)
        predictions[ENS] = ensemble(predictions[CUR], predictions[LGBM])
        predictions[ENSP] = ensemble(predictions[PERS], predictions[LGBM])
        rows.append((window, predictions))
    scores = risk_models.predict([w for w, _ in rows]) if rows else {}
    for index, (_, predictions) in enumerate(rows):
        predictions["risk"] = {name: float(values[index]) for name, values in scores.items()}
        predictions["risk"][CUR] = predictions[CUR]["risk"]
    log(f"{cutoff}: оценено {len(rows)} окон за {time.time() - started:.0f} c")
    info = {
        "train_windows": len(fit), "train_rows": regressor.rows, "train_positive_windows": risk_models.positives,
        "train_new_gap_positive_windows": risk_models.new_gap_positives,
        "control_windows": len(control.get(cutoff, [])), "scored_windows": len(rows),
        "product_failures": dict(failures),
    }
    if export_dir is not None:
        info.update(save_and_check(regressor, risk_models, rows, scores,
                                   export_dir / "models" / cutoff.isoformat()))
    return rows, info


def regression_reports(rows):
    return {name: scoring.regression([(w, p[name]) for w, p in rows]) for name in REGRESSION}


def select(rows, common=True, new_gap=False):
    """common: только окна с доступной вероятностью продукта; new_gap: только старт с остатком >= 0."""
    return [(w, p) for w, p in rows
            if (not common or p["risk"][CUR] is not None) and (not new_gap or w.opening >= 0)]


def pairs(rows, name):
    return [(w.label, p["risk"][name]) for w, p in rows]


def risk_block(validation_rows, holdout_rows, names, new_gap):
    """Пороги — на validation этой же цели; holdout на общей выборке и на всех доступных окнах."""
    val, hold = select(validation_rows, new_gap=new_gap), select(holdout_rows, new_gap=new_gap)
    thresholds = {n: scoring.choose_threshold(pairs(val, n)) for n in names}
    every = select(holdout_rows, common=False, new_gap=new_gap)
    block = {
        "thresholds_from_validation": thresholds,
        # При нуле событий на validation F1 везде 0 и порог формально 0.95 — это не выбор, а вырожденный случай.
        "validation_positives": int(sum(w.label for w, _ in val)),
        "availability_current": {"validation": [len(val), len(select(validation_rows, False, new_gap))],
                                 "holdout": [len(hold), len(every)]},
        "validation": {n: scoring.risk(pairs(val, n), thresholds[n]) for n in names},
        "holdout": {n: scoring.risk(pairs(hold, n), thresholds[n]) for n in names},
        "holdout_all_available": {n: scoring.risk(pairs(every, n), thresholds[n]) for n in names if n != CUR},
    }
    return block, val, hold


def brier_ci(rows, name, reference):
    return scoring.paired_brier_bootstrap([(w.company, w.label, p["risk"][name]) for w, p in rows],
                                          [(w.company, w.label, p["risk"][reference]) for w, p in rows])


def examples(rows):
    """Нейтральный выбор графиков: квартили ошибки текущей модели и новый разрыв, если он есть."""
    errors = sorted((float(np.abs(p[CUR]["p50"] - w.truth[:, 2]).mean()), i) for i, (w, p) in enumerate(rows))
    picks = [(errors[int(q * (len(errors) - 1))][1], f"{label} ошибка текущей модели")
             for q, label in ((0.25, "низкая"), (0.5, "медианная"), (0.75, "высокая"))]
    used = {i for i, _ in picks}
    fresh = [i for i, (w, _) in enumerate(rows) if w.label and w.opening >= 0 and i not in used]
    negative = [i for i, (w, _) in enumerate(rows) if w.label and i not in used]
    if fresh:
        picks.append((fresh[0], "новый разрыв при старте ≥ 0"))
    elif negative:
        picks.append((negative[0], "минус в горизонте, старт уже отрицательный"))
    else:
        picks.append((errors[int(0.9 * (len(errors) - 1))][1], "ошибка текущей модели 90-й перцентиль"))
    return [{"window": rows[i][0], "predictions": rows[i][1], "reason": reason} for i, reason in picks]


def clean(value):
    # NaN/inf невалидны в JSON: неопределённая метрика публикуется как null.
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def manifest():
    paths = [*sorted((ROOT / "evaluation/model_compare").glob("*.py")),
             ROOT / "evaluation/MODEL-COMPARE-PLAN.md", ROOT / "evaluation/MODEL-COMPARE-PLAN-v2.md"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in paths if p.exists()}


def regression_verdict(validation, holdout, per_cutoff, holdout_rows):
    best = min(CANDIDATES, key=lambda name: validation[name]["balance"]["mae"])
    bootstrap = {f"{name} vs {ref}": scoring.paired_bootstrap([(w, p[name]) for w, p in holdout_rows],
                                                              [(w, p[ref]) for w, p in holdout_rows])
                 for name in CANDIDATES for ref in REFERENCES}
    cut = {c.isoformat(): per_cutoff[c.isoformat()] for c in VALIDATION}
    wins = sum(int(report[best]["balance"]["mae"] < report[PERS]["balance"]["mae"]) for report in cut.values())
    mae = {phase: {ref: report[best]["balance"]["mae"] < report[ref]["balance"]["mae"] for ref in REFERENCES}
           for phase, report in (("validation", validation), ("holdout", holdout))}
    ci_ok = {ref: bootstrap[f"{best} vs {ref}"]["ci95"][1] < 0 for ref in (CUR, PERS)}
    return {
        "selected_on_validation": best, "validation_cutoffs_won_vs_persistence": wins,
        "beats_references_mae": mae, "holdout_ci_upper_below_zero": ci_ok,
        "better_than_product": bool(all(mae["validation"].values()) and wins >= 3 and all(mae["holdout"].values())
                                    and all(ci_ok.values())),
    }, bootstrap


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--companies", help="Только для smoke: список company_id через запятую")
    parser.add_argument("--smoke", action="store_true", help="Мало деревьев: проверка кода, не результат")
    parser.add_argument("--export", action="store_true",
                        help="Сохранить веса, прогнозы по окнам, схемы обучения и признаков, манифест")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.time()

    def log(message):
        print(f"[{time.time() - started:6.0f}s] {message}", flush=True)

    code = manifest()
    companies = set(args.companies.split(",")) if args.companies else None
    transactions, balances = load(args.zip, companies)
    log(f"загружено компаний: {len(transactions)}")
    train, control, skipped, train_skipped = build(transactions, balances, log)
    log(f"обучающих окон: {len(train)}, контрольных: {sum(map(len, control.values()))}")

    export_dir = args.output if args.export else None
    per_cutoff_rows, info = {}, {}
    for cutoff in (*VALIDATION, HOLDOUT):
        per_cutoff_rows[cutoff], info[cutoff.isoformat()] = predict_cutoff(train, control, cutoff, args.smoke, log,
                                                                           export_dir)
    validation_rows = [row for c in VALIDATION for row in per_cutoff_rows[c]]
    holdout_rows = per_cutoff_rows[HOLDOUT]

    validation = regression_reports(validation_rows)
    holdout = regression_reports(holdout_rows)
    per_cutoff = {c.isoformat(): regression_reports(per_cutoff_rows[c]) for c in (*VALIDATION, HOLDOUT)}
    cohorts = {cohort: {name: scoring.regression([(w, p[name]) for w, p in holdout_rows if w.cohort == cohort])
                        for name in (BASE, CUR, PERS, LGBM, ENS, ENSP)}
               for cohort in sorted({w.cohort for w, _ in holdout_rows})}
    verdict, bootstrap = regression_verdict(validation, holdout, per_cutoff, holdout_rows)

    any_negative, any_val, any_hold = risk_block(validation_rows, holdout_rows, RISK, new_gap=False)
    new_gap, _, gap_hold = risk_block(validation_rows, holdout_rows, NEW_GAP, new_gap=True)
    any_negative["brier_ci_holdout"] = {f"{n} vs {ref}": brier_ci(any_hold, n, ref)
                                        for n in RISK_TRAINED for ref in (CUR, RISK_PERSISTENCE)}
    new_gap["brier_ci_holdout"] = {f"{n} vs {CUR}": brier_ci(gap_hold, n, CUR) for n in NEW_GAP[1:]}
    brier = {phase: {n: any_negative[phase][n]["at_0_5"]["metrics"]["brier"] for n in RISK}
             for phase in ("validation", "holdout")}
    risk_verdict = {
        n: bool(all(None not in (brier[ph][n], brier[ph][CUR], brier[ph][RISK_PERSISTENCE])
                    and brier[ph][n] < min(brier[ph][CUR], brier[ph][RiskModels.NAMES[3]], brier[ph][RISK_PERSISTENCE])
                    for ph in brier)
                and (any_negative["brier_ci_holdout"][f"{n} vs {RISK_PERSISTENCE}"]["ci95"][1] or 0) < 0)
        for n in RISK_TRAINED
    }

    reference = {phase: {"windows": report[REF]["windows"], "mae_rub": report[REF]["balance"]["mae"],
                         "b4_windows": B4[phase][0], "b4_mae_rub": B4[phase][1],
                         "matches_b4": bool(report[REF]["windows"] == B4[phase][0]
                                            and abs(report[REF]["balance"]["mae"] - B4[phase][1]) < 0.01)}
                 for phase, report in (("validation", validation), ("holdout", holdout))}
    failures = sum(sum(item["product_failures"].values()) for item in info.values())
    stand = {"product_failures_total": failures,
             "reference_matches_b4": all(item["matches_b4"] for item in reference.values())}
    if failures or not stand["reference_matches_b4"]:
        log(f"ВНИМАНИЕ: стенд не прошёл самопроверку {stand}; результаты нельзя считать сопоставимыми с B4")

    curves = {n: scoring.curves(pairs(any_hold, n)) for n in RISK}
    gap_curves = {n: scoring.curves(pairs(gap_hold, n)) for n in NEW_GAP}
    calibration = {"validation": {n: scoring.curves(pairs(any_val, n)) for n in RISK}, "holdout": curves}
    thresholds, gap_thresholds = any_negative["thresholds_from_validation"], new_gap["thresholds_from_validation"]
    out = args.output
    charts = [
        plots.forecast_examples(examples(holdout_rows), out / "forecast_examples.png", (CUR, ENS), (PERS,)),
        plots.mae_by_horizon(holdout, (BASE, NAIVE, CUR, PERS, LGBM, ENS, ENSP), out / "mae_by_horizon.png"),
        plots.mae_by_cutoff(per_cutoff, (CUR, PERS, LGBM, ENS, ENSP), out / "mae_by_cutoff.png"),
        plots.confusion_grid([(f"{n} · порог {thresholds[n]}", any_negative["holdout"][n]["at_validation_threshold"]
                               ["confusion_matrix"]) for n in RISK],
                             "Минус за 30 дней, holdout: порог выбран на validation", out / "confusion_risk.png"),
        plots.confusion_grid([(f"{n} · порог {gap_thresholds[n]}", new_gap["holdout"][n]["at_validation_threshold"]
                               ["confusion_matrix"]) for n in NEW_GAP],
                             "Новый разрыв (старт ≥ 0), holdout: порог выбран на validation новых разрывов",
                             out / "confusion_new_gap.png"),
        plots.confusion_grid([(n, holdout[n]["daily_negative_by_median"]["confusion_matrix"])
                              for n in (CUR, PERS, LGBM, ENS, ENSP)],
                             "Ежедневный минус по медиане p50, holdout (единица — день)",
                             out / "confusion_daily_median.png"),
        plots.roc_pr(curves, out / "roc_pr.png"),
        plots.roc_pr(gap_curves, out / "roc_pr_new_gap.png", "новые разрывы, holdout"),
        plots.calibration(calibration, out / "calibration.png"),
    ]

    result = {
        "protocol": "evaluation/MODEL-COMPARE-PLAN-v2.md",
        "smoke": args.smoke, "companies_filter": sorted(companies) if companies else None,
        "dataset_sha256": hashlib.sha256(args.zip.read_bytes()).hexdigest(),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "packages": {n: version(n) for n in ("lightgbm", "scikit-learn", "numpy", "matplotlib")}},
        "code_sha256_lf": code,
        "runtime_seconds": round(time.time() - started),
        "windows": {"train": len(train), "skipped_train": train_skipped, "skipped_control": skipped,
                    "per_cutoff": info},
        "reference_reproduction": reference,
        "stand_checks": stand,
        "regression": {"validation": validation, "holdout": holdout, "per_cutoff": per_cutoff,
                       "holdout_by_cohort": cohorts, "verdict": verdict, "paired_bootstrap_holdout": bootstrap},
        "risk_any_negative": {**any_negative, "verdict_v2": risk_verdict, "curves_holdout": curves},
        "risk_new_gap": {**new_gap, "curves_holdout": gap_curves},
        "charts": charts,
        "limitations": [
            "Сентябрь 2026 уже просматривался в B4/B6, v1 и аудите: holdout ретроспективный, не нетронутый.",
            "Временная проверка тех же 150 компаний; отдельного split по новым компаниям нет.",
            "planned_events пусты: качество учёта будущих счетов не измеряется (как в B4).",
            "Окна одной компании зависимы; доверительные интервалы — bootstrap по компаниям.",
            "Новых разрывов на holdout единицы: качество предупреждения нового разрыва не оценивается.",
            "Вероятности не калибровались; низкий Brier не доказывает калибровку.",
            "R² и WAPE остатка считаются по всем окнам вместе; нормированная MAE показана отдельно.",
            "Квантили ансамбля 2.1 + LightGBM — усреднение квантилей, а не квантили смеси.",
            "Медиана остатка LightGBM и прогноз средних потоков — разные статистики и не обязаны сходиться.",
        ],
    }
    path = out / "results.json"
    path.write_text(json.dumps(clean(result), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")
    log(f"готово: {path}")
    if args.export:
        export.write_predictions(per_cutoff_rows, out)
        scheme = export.training_scheme(train, control, transactions, train_skipped, skipped)
        for name, value in (("training_scheme.json", scheme), ("feature_schema.json", export.feature_schema())):
            (out / name).write_text(json.dumps(clean(value), ensure_ascii=False, indent=1), encoding="utf-8")
        export.write_notebook(out / "colab_run.ipynb")
        export.write_manifest(out, {"dataset_sha256": result["dataset_sha256"], "code_sha256_lf": code,
                                    "environment": result["environment"]})
        log(f"выгрузка: {out}")
    summary = {name: {"validation_mae": validation[name]["balance"]["mae"],
                      "holdout_mae": holdout[name]["balance"]["mae"]} for name in REGRESSION}
    print(json.dumps(clean({"summary": summary, "regression_verdict": verdict, "reference": reference,
                            "stand_checks": stand, "risk_verdict": risk_verdict}), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
