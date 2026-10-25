"""Выгрузка для внешней проверки: прогнозы по окнам, схемы обучения и признаков, ноутбук, манифест."""

import csv
import hashlib
import json
from datetime import timedelta

import numpy as np

from .features import REGRESSION_FEATURES, RISK_FEATURES
from .models import CLASSIFIER, MIN_QUANTILES, QUANTILES, REGRESSOR, SEED, WINDOW_REGRESSOR
from .organizers import FIRST_TRAIN, HOLDOUT, LOOKBACK, TRAIN_GAP, TRAIN_STEP, VALIDATION, train_for

# Латинские имена колонок CSV для моделей отчёта.
TAGS = {"Baseline (повтор недели)": "baseline_week", "Сезонный naive (месяц)": "naive_month",
        "Эталон 1.0-w84 (B4)": "ref_1_0_w84", "Текущая 2.1-w84": "current_2_1_w84",
        "Persistence (остаток не меняется)": "persistence", "LightGBM v2": "lightgbm_v2",
        "Ансамбль 2.1 + LightGBM v2": "ensemble_2_1_lightgbm_v2",
        "Ансамбль persistence + LightGBM v2": "ensemble_persistence_lightgbm_v2"}
RISK_TAGS = {"Текущая 2.1-w84": "current_2_1_w84", "LightGBM-классификатор": "lightgbm_classifier",
             "Логистическая регрессия": "logistic", "LightGBM квантили минимума": "lightgbm_min_quantiles",
             "Константа (частота train)": "constant_prior", "Persistence (знак остатка)": "persistence_sign",
             "Новый разрыв: LightGBM": "new_gap_lightgbm", "Новый разрыв: логистическая": "new_gap_logistic",
             "Новый разрыв: частота train": "new_gap_prior"}


def _rub(value):
    # Копейки -> рубли без округления; нет интервала у модели -> пустая ячейка.
    return "" if value is None or not np.isfinite(value) else repr(float(value) / 100)


def _prob(value):
    return "" if value is None else repr(float(value))


def write_predictions(rows_by_cutoff, folder):
    """Одна строка daily = окно × день горизонта; одна строка risk = окно."""
    daily_fields = ["company_id", "as_of", "phase", "cohort", "h", "date", "opening_rub",
                    "actual_inflow_rub", "actual_outflow_rub", "actual_balance_rub"]
    for tag in TAGS.values():
        daily_fields += [f"{tag}_{k}_rub" for k in ("inflow", "outflow", "p10", "p50", "p90")]
    risk_fields = ["company_id", "as_of", "phase", "cohort", "opening_rub", "new_gap_eligible",
                   "label_any_negative_30d", "first_negative_h", "min_balance_rub",
                   *(f"prob_{tag}" for tag in RISK_TAGS.values())]
    with (folder / "predictions_daily.csv").open("w", newline="", encoding="utf-8") as daily, \
            (folder / "predictions_risk.csv").open("w", newline="", encoding="utf-8") as risk:
        daily_writer, risk_writer = csv.writer(daily), csv.writer(risk)
        daily_writer.writerow(daily_fields)
        risk_writer.writerow(risk_fields)
        for cutoff, rows in rows_by_cutoff.items():
            phase = "holdout" if cutoff == HOLDOUT else "validation"
            for window, predictions in rows:
                key = [window.company, window.as_of.isoformat(), phase, window.cohort]
                for k, actual in enumerate(window.truth):
                    line = [*key, k + 1, (window.as_of + timedelta(days=k + 1)).isoformat(), _rub(window.opening),
                            *(_rub(v) for v in actual)]
                    for name in TAGS:
                        p = predictions[name]
                        line += [_rub(p["inc"][k]), _rub(p["out"][k]),
                                 *(_rub(p[q][k]) if p[q] is not None else "" for q in ("p10", "p50", "p90"))]
                    daily_writer.writerow(line)
                negative = np.flatnonzero(window.truth[:, 2] < 0)
                risk_writer.writerow([*key, _rub(window.opening), int(window.opening >= 0), window.label,
                                      int(negative[0]) + 1 if negative.size else "", _rub(window.truth[:, 2].min()),
                                      *(_prob(predictions["risk"][name]) for name in RISK_TAGS)])


def training_scheme(train, control, companies, train_skipped, control_skipped):
    scheme = {
        "rule": "Окно as_of идёт в обучение среза c, только если as_of + 37 дней <= c: 30 дней цели и 7 дней "
                "на подтверждающий остаток закончились до среза. Незавершённые цели не используются.",
        "lookback_days": LOOKBACK, "train_step_days": TRAIN_STEP, "first_train_as_of": FIRST_TRAIN.isoformat(),
        "gap_days": TRAIN_GAP, "train_windows_skipped_by_reason": train_skipped,
        "control_windows_skipped": control_skipped, "cutoffs": {},
    }
    for cutoff in (*VALIDATION, HOLDOUT):
        fit = train_for(train, cutoff)
        dates = sorted({w.as_of for w in fit})
        used = {w.company for w in fit}
        scheme["cutoffs"][cutoff.isoformat()] = {
            "train_windows": len(fit), "positive_windows": int(sum(w.label for w in fit)),
            "as_of_first": dates[0].isoformat(), "as_of_last": dates[-1].isoformat(),
            "latest_target_end": (dates[-1] + timedelta(days=30)).isoformat(),
            "as_of_dates": [d.isoformat() for d in dates], "companies_in_train": len(used),
            "companies_without_train_windows": sorted(set(companies) - used),
            "control_companies_not_in_train": sorted({w.company for w in control.get(cutoff, [])} - used),
        }
    return scheme


def feature_schema():
    return {
        "regression_features": list(REGRESSION_FEATURES), "risk_features": list(RISK_FEATURES),
        "regression_row": "Одна строка = (окно, шаг h = 1..30); признаки окна повторяются на каждом шаге.",
        "scale": "s = max(10000 коп., средний дневной приток за 84 дня, средний дневной отток за 84 дня); "
                 "_s = деление на s. Дни до первой операции компании — NaN и в средних не участвуют.",
        "missing": "NaN — неизвестное значение: LightGBM обрабатывает сам, логистика — медианой train.",
        "quality_mask": "Дни окна до последней несверки остатка, известной на as_of, — NaN (потоки дня несверки "
                        "тоже); признаки unreconciled_days84 и days_since_unreconciled. Как quality.py продукта.",
        "targets": {
            "balance_delta_q*": "(B(as_of+h) - B(as_of)) / s без обрезки, objective quantile",
            "inflow_mean / outflow_mean": "дневной поток / s без обрезки, objective huber, alpha=1.0",
            "risk_lgbm_classifier / logistic": "1, если хотя бы один EOD < 0 за 30 дней, иначе 0; все окна",
            "new_gap_lgbm_classifier / new_gap_logistic": "та же метка, обучение только на окнах с B(as_of) >= 0",
            "risk_min_balance_q*": "min_h B(as_of+h) / s без обрезки, objective quantile",
        },
        "postprocessing": {
            "balance": "p10/p50/p90 = B(as_of) + s * квантили, квантили сортируются по возрастанию",
            "flows": "max(0, s * прогноз)",
            "min_quantiles_probability": "P = np.interp(0, отсортированные квантили минимума, уровни, "
                                         "left=0.005, right=0.995)",
            "persistence": "частота минуса в train отдельно для отрицательного и неотрицательного старта",
        },
        "ensemble": "Два ансамбля с весами 0.5/0.5, заданными до запуска: 2.1 + LightGBM v2 (p10, p50, p90 — "
                    "усреднение квантилей, inflow, outflow) и persistence + LightGBM v2 (только p50 и потоки).",
        "thresholds": "Порог 0.5 — порог продукта. Второй порог выбран на validation по максимуму F1 "
                      "(сетка 0.05–0.95) отдельно для «любой минус» и для новых разрывов; на holdout не подбирался.",
        "parameters": {"regressor": REGRESSOR, "window_regressor": WINDOW_REGRESSOR, "classifier": CLASSIFIER,
                       "quantiles": list(QUANTILES), "min_quantiles": list(MIN_QUANTILES),
                       "logistic": {"C": 0.1, "max_iter": 5000, "solver": "lbfgs"}},
        "seed": SEED,
    }


def write_notebook(path):
    """Ноутбук Colab, повторяющий запуск этого пакета."""
    cells = [
        ("markdown", "# CashCast: сравнение моделей прогноза\nЗагрузите `cashcast-code.zip` и "
                     "`cashflow_dataset_participants.zip`, затем выполните ячейки по порядку."),
        ("code", "from google.colab import files\nup = files.upload()\nprint({k: len(v) for k, v in up.items()})"),
        ("code", "import hashlib, pathlib, shutil, zipfile\nW = pathlib.Path('/content/cashcast')\n"
                 "zipfile.ZipFile('/content/cashcast-code.zip').extractall(W)\n(W / 'data').mkdir(exist_ok=True)\n"
                 "shutil.move('/content/cashflow_dataset_participants.zip', W / 'data')\n"
                 "z = W / 'data/cashflow_dataset_participants.zip'\n"
                 "print(hashlib.sha256(z.read_bytes()).hexdigest())  # e753802b...9987"),
        ("code", "!cd /content/cashcast && python -m evaluation.model_compare.run "
                 "--zip data/cashflow_dataset_participants.zip --output out --export 2>&1 | tee run.log"),
        ("code", "!cd /content/cashcast && python -m evaluation.model_compare.predict "
                 "--zip data/cashflow_dataset_participants.zip --models out/models/2026-08-31 "
                 "--company C001 --as-of 2026-08-31"),
        ("code", "!cd /content/cashcast && zip -qr /content/out.zip out run.log\n"
                 "from google.colab import files\nfiles.download('/content/out.zip')"),
    ]
    notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"name": "python3",
                                                                                "display_name": "Python 3"}},
                "cells": [{"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True),
                           **({"outputs": [], "execution_count": None} if kind == "code" else {})}
                          for kind, text in cells]}
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")


def write_manifest(folder, extra):
    files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    (folder / "manifest.json").write_text(json.dumps({**extra, "files_sha256": files}, ensure_ascii=False,
                                                     indent=1), encoding="utf-8")
