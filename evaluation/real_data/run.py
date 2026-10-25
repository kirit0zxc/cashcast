"""Воспроизводимое временное сравнение, агрегаты без банковского текста и сырых строк."""

import argparse
import json
from datetime import date
from pathlib import Path
from statistics import mean

from .datasets import BerkaAudit, MoneyVis
from .models import FlowBaseline, FlowCandidate
from .provenance import manifest


def measure(model, days, year, horizon):
    folds = []
    for i in range(84, len(days) - horizon, 30):
        # Вся цель должна принадлежать своей фазе, граница split не пересекается.
        if days[i + 1].date.year != year or days[i + horizon].date.year != year:
            continue
        predicted = model.predict(days[: i + 1], horizon)
        actual = days[i + 1 : i + 1 + horizon]
        eligible = days[i].balance >= 0
        truth = any(d.balance < 0 for d in actual)
        alert = any(d.balance < 0 for d in predicted)
        folds.append(
            {
                "balance_mae": mean(
                    abs(a.balance - p.balance)
                    for a, p in zip(actual, predicted, strict=True)
                ),
                "inflow_mae": mean(
                    abs(a.incoming - p.incoming)
                    for a, p in zip(actual, predicted, strict=True)
                ),
                "outflow_mae": mean(
                    abs(a.outgoing - p.outgoing)
                    for a, p in zip(actual, predicted, strict=True)
                ),
                "end_balance_error": abs(actual[-1].balance - predicted[-1].balance),
                "eligible": eligible,
                "truth": truth,
                "alert": alert,
            }
        )
    if not folds:
        raise ValueError("Нет полных окон для оценки")
    selected = [f for f in folds if f["eligible"]]
    tp = sum(f["truth"] and f["alert"] for f in selected)
    fp = sum(not f["truth"] and f["alert"] for f in selected)
    fn = sum(f["truth"] and not f["alert"] for f in selected)
    tn = len(selected) - tp - fp - fn
    return {
        "folds": len(folds),
        "new_gap_eligible_folds": len(selected),
        **{
            key + "_source_units": round(mean(f[key] for f in folds) / 100, 4)
            for key in ("balance_mae", "inflow_mae", "outflow_mae", "end_balance_error")
        },
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": tp / (tp + fn) if tp + fn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "roc_auc": None,
        "probability_estimated": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--moneyvis", type=Path, required=True)
    parser.add_argument("--berka", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    args = parser.parse_args()
    days, audit = MoneyVis.read(args.moneyvis)
    train = [d for d in days if d.date <= date(2020, 12, 31)]
    candidate = FlowCandidate().fit(train)
    models = {
        "catboost": candidate,
        "last_week": FlowBaseline("last_week"),
        "weekday84": FlowBaseline("weekday84"),
    }
    results = {
        str(year): {
            str(h): {name: measure(m, days, year, h) for name, m in models.items()}
            for h in (7, 14, 30)
        }
        for year in (2021, 2022)
    }
    gates = {}
    for h, values in results["2021"].items():
        baseline = min(
            values[n]["balance_mae_source_units"] for n in ("last_week", "weekday84")
        )
        gates[h] = values["catboost"]["balance_mae_source_units"] <= 0.95 * baseline
    args.weights.mkdir(parents=True, exist_ok=True)
    for name, model in zip(("incoming", "outgoing"), candidate.models, strict=True):
        model.save_model(str(args.weights / (name + ".cbm")))
    import catboost

    result = {
        "protocol": "evaluation/REAL-DATA-PLAN.md",
        "dataset": audit,
        "model_version": candidate.VERSION,
        "catboost_version": catboost.__version__,
        "train_end": train[-1].date.isoformat(),
        "validation_year": 2021,
        "test_year": 2022,
        "metrics": results,
        "validation_gate_by_horizon": gates,
        "production_activated": False,
        "limitations": [
            "one_retail_account_not_sme",
            "calendar_completeness_assumed",
            "no_new_gap_positives_in_moneyvis",
            "no_probability_model_or_roc_auc",
            "baselines_are_not_full_product_guarded_model",
        ],
        "berka_audit": BerkaAudit.read(args.berka) if args.berka else None,
        "reproducibility": manifest(
            [args.weights / "incoming.cbm", args.weights / "outgoing.cbm"]
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"output": str(args.output), "gates": gates, "berka": result["berka_audit"]}
        )
    )


if __name__ == "__main__":
    main()
