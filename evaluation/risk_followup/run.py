"""Фиксированная повторная проверка без обучения/перезаписи исходной модели PR55."""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

from evaluation.real_data.risk import build_folds, metrics

from .policy import InterceptCalibrator, choose_operating_point, reliability
from .uncertainty import account_bootstrap


def report(rows, scores, threshold, prior):
    labels = [r[1] for r in rows]
    output = metrics(labels, scores, threshold, prior)
    output["threshold"] = threshold
    output["reliability"] = reliability(labels, scores)
    output["uncertainty"] = account_bootstrap([r[2] for r in rows], labels, scores, threshold, prior)
    output["liquidity_slices"] = {}
    output["liquidity_definition"] = "opening_balance / max(100 source minor units, mean_expense_84)"
    for name, lower, upper in (
        ("ratio_under_7", 0, 7),
        ("ratio_7_to_30", 7, 30),
        ("ratio_30_or_more", 30, float("inf")),
    ):
        ids = [i for i, r in enumerate(rows) if lower <= r[0][0] < upper]
        output["liquidity_slices"][name] = metrics([labels[i] for i in ids], [scores[i] for i in ids], threshold, prior)
    return output


def main():
    from catboost import CatBoostClassifier

    parser = argparse.ArgumentParser()
    parser.add_argument("--berka", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--original-report", type=Path, default=Path("evaluation/berka-risk-results.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    old = json.loads(args.original_report.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(args.berka.read_bytes()).hexdigest()
    weights_hash = hashlib.sha256(args.weights.read_bytes()).hexdigest()
    if source_hash != old["source_sha256"] or weights_hash != old["reproducibility"]["weights_sha256"]["risk.cbm"]:
        raise ValueError("Источник или модель не совпадают с замороженным PR55")
    # Предыдущий code manifest остаётся проверяемым: loader/признаки не меняются.
    for filename, expected in old["reproducibility"]["source_sha256"].items():
        path = Path(__file__).parents[1] / "real_data" / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Изменился код исходного эксперимента")
    groups, audit = build_folds(args.berka)
    prior = mean(r[1] for r in groups["train"])
    if len(groups["train"]) != old["train_folds"] or prior != old["train_prior"]:
        raise ValueError("Обучающая выборка изменилась")
    model = CatBoostClassifier()
    model.load_model(str(args.weights))
    validation = groups["validation"]
    fit = [r for r in validation if hashlib.sha256(r[2].encode()).digest()[1] % 2 == 0]
    selection = [r for r in validation if hashlib.sha256(r[2].encode()).digest()[1] % 2 == 1]
    if not fit or not selection:
        raise ValueError("Недостаточно счетов для раздельной калибровки и выбора порога")
    fit_scores = list(map(float, model.predict_proba([r[0] for r in fit])[:, 1]))
    selection_scores = list(map(float, model.predict_proba([r[0] for r in selection])[:, 1]))
    calibrator = InterceptCalibrator.fit([r[1] for r in fit], fit_scores)
    candidates = {"raw": selection_scores}
    if calibrator:
        candidates["intercept_calibrated"] = calibrator.transform(selection_scores)
    checks = {}
    for name, scores in candidates.items():
        threshold_result = choose_operating_point([r[1] for r in selection], scores, prior)
        checks[name] = {
            "operating_point": threshold_result,
            "at_original_threshold": report(selection, scores, 0.05, prior),
        }
    allowed = [
        (name, value["operating_point"]["selected"])
        for name, value in checks.items()
        if value["operating_point"]["selected"] is not None
        and value["operating_point"]["selected"]["brier"] < value["operating_point"]["selected"]["constant_brier"]
    ]
    selected = min(allowed, key=lambda pair: (pair[1]["brier"], pair[0])) if allowed else None
    retrospective = {}
    for name in ("test_development_accounts", "test_unseen_accounts"):
        rows = groups[name]
        raw = list(map(float, model.predict_proba([r[0] for r in rows])[:, 1]))
        retrospective[name] = {"v1_threshold_005": report(rows, raw, 0.05, prior), "selected": None}
        if selected:
            scores = calibrator.transform(raw) if selected[0] == "intercept_calibrated" else raw
            retrospective[name]["selected"] = report(rows, scores, selected[1]["threshold"], prior)
    output = {
        "protocol": "evaluation/RISK-FOLLOWUP-PLAN.md",
        "test_is_retrospective": True,
        "original_report_sha256": hashlib.sha256(args.original_report.read_bytes()).hexdigest(),
        "source_sha256": source_hash,
        "weights_sha256": weights_hash,
        "audit": audit,
        "calibration": {
            "folds": len(fit),
            "positives": sum(r[1] for r in fit),
            "accounts": len({r[2] for r in fit}),
            "intercept": calibrator.intercept if calibrator else None,
            "available": calibrator is not None,
        },
        "selection": {
            "folds": len(selection),
            "positives": sum(r[1] for r in selection),
            "accounts": len({r[2] for r in selection}),
            "candidates": checks,
        },
        "selected": {"method": selected[0], "threshold": selected[1]["threshold"]} if selected else None,
        "retrospective": retrospective,
        "release": {
            "allowed": False,
            "reasons": (["no_candidate_passes_selection"] if not selected else [])
            + ["no_target_sme_validation", "test_previously_inspected"],
        },
        "followup_source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({"calibration": output["calibration"], "selected": output["selected"], "release": output["release"]})
    )


if __name__ == "__main__":
    main()
