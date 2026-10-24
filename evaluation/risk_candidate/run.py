"""Обучение одного заранее заданного кандидата и честное парное сравнение с v1."""

import argparse
import hashlib
import json
import platform
import random
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path

from evaluation.real_data.models import SEED
from evaluation.real_data.risk import metrics
from evaluation.risk_followup.uncertainty import account_bootstrap

from .data import CandidateDataset

THRESHOLDS = (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5)
PARAMETERS = {"iterations": 500, "depth": 4, "learning_rate": 0.04, "l2_leaf_reg": 8,
              "loss_function": "Logloss", "random_seed": SEED, "thread_count": 2,
              "verbose": False, "allow_writing_files": False}


def source_manifest(root):
    paths = [*Path(__file__).parent.glob("*.py"),
             *root.joinpath("evaluation/real_data").glob("*.py"),
             root / "evaluation/risk_followup/uncertainty.py",
             root / "evaluation/RISK-CANDIDATE-V2-PLAN.md"]
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest()
            for p in sorted(paths)}


class CandidateComparison:
    @staticmethod
    def select(labels, scores, prior):
        rows = [{**metrics(labels, scores, threshold, prior), "threshold": threshold} for threshold in THRESHOLDS]
        allowed = [row for row in rows if row["fpr"] is not None and row["fpr"] <= 0.01]
        return max(allowed, key=lambda row: (row["f2"], row["threshold"])) if allowed else None, rows

    @staticmethod
    def improved(candidate, baseline):
        return bool(candidate and candidate["average_precision"] is not None
                    and candidate["average_precision"] > baseline["average_precision"]
                    and candidate["brier"] <= baseline["brier"] and candidate["f2"] > baseline["f2"])

    @staticmethod
    def policy(row):
        return bool(row and row["positives"] >= 10 and row["precision"] is not None
                    and row["precision"] >= 0.5 and row["recall"] >= 0.5 and row["fpr"] <= 0.01
                    and row["brier"] < row["constant_brier"])

    @staticmethod
    def paired_brier(rows, scores, baseline):
        # Пересэмплируем целые счета, сохраняя парность ошибок и зависимость окон.
        by_account = defaultdict(list)
        for row, score, old in zip(rows, scores, baseline, strict=True):
            by_account[row[2]].append((score - row[1]) ** 2 - (old - row[1]) ** 2)
        values = [(sum(errors), len(errors)) for _, errors in sorted(by_account.items())]
        rng = random.Random(SEED)  # noqa: S311 — воспроизводимый bootstrap, не секреты.
        replicates = []
        for _ in range(500):
            draw = rng.choices(values, k=len(values))
            replicates.append(sum(v[0] for v in draw) / sum(v[1] for v in draw))
        replicates.sort()
        return {"method": "paired_account_bootstrap", "replicates": 500, "seed": SEED,
                "estimate": sum(v[0] for v in values) / sum(v[1] for v in values),
                "ci95": [replicates[12], replicates[487]], "negative_favors_candidate": True}

    @classmethod
    def evaluate(cls, rows, scores, baseline, threshold, prior, bootstrap=False):
        labels = [r[1] for r in rows]
        result = {
            "windows": len(rows), "accounts": len({r[2] for r in rows}),
            "positive_accounts": len({r[2] for r in rows if r[1]}),
            "baseline": {**metrics(labels, baseline, 0.05, prior), "threshold": 0.05},
            "candidate": {**metrics(labels, scores, threshold, prior), "threshold": threshold}
            if threshold is not None else None,
        }
        if bootstrap and threshold is not None:
            result["uncertainty"] = account_bootstrap([r[2] for r in rows], labels, scores, threshold, prior)
            result["paired_brier_candidate_minus_v1"] = cls.paired_brier(rows, scores, baseline)
        return result


def main():
    from catboost import CatBoostClassifier

    parser = argparse.ArgumentParser()
    parser.add_argument("--berka", required=True, type=Path)
    parser.add_argument("--baseline-weights", required=True, type=Path)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    code_manifest = source_manifest(root)
    environment = {"python": platform.python_version(),
                   "packages": {name: version(name) for name in ("catboost", "numpy", "pandas", "scipy")}}
    old = json.loads((root / "evaluation/berka-risk-results.json").read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(args.berka.read_bytes()).hexdigest()
    baseline_sha = hashlib.sha256(args.baseline_weights.read_bytes()).hexdigest()
    if source_sha != old["source_sha256"] or baseline_sha != old["reproducibility"]["weights_sha256"]["risk.cbm"]:
        raise ValueError("Исходные данные или веса v1 изменились")
    print("building_folds", flush=True)
    groups, audit = CandidateDataset.build(args.berka)
    train = groups["train"]
    print(json.dumps({"train_windows": len(train), "train_positives": sum(r[1] for r in train)}), flush=True)
    # Сравниваем Brier с той же заранее закреплённой частотой v1, а не с частотой test.
    prior = old["train_prior"]
    candidate = CatBoostClassifier(**PARAMETERS)
    candidate.fit([r[0] for r in train], [r[1] for r in train], sample_weight=CandidateDataset.weights(train))
    baseline = CatBoostClassifier()
    baseline.load_model(str(args.baseline_weights))
    validation = groups["validation"]
    scores = list(map(float, candidate.predict_proba([r[0] for r in validation])[:, 1]))
    old_scores = list(map(float, baseline.predict_proba([r[3] for r in validation])[:, 1]))
    selected, candidates = CandidateComparison.select([r[1] for r in validation], scores, prior)
    threshold = selected["threshold"] if selected else None
    result = {"validation": CandidateComparison.evaluate(validation, scores, old_scores, threshold, prior)}
    # Порог уже выбран; 1998 не участвует ни в обучении, ни в выборе.
    for name in ("test_development_accounts", "test_unseen_accounts"):
        rows = groups[name]
        current = list(map(float, candidate.predict_proba([r[0] for r in rows])[:, 1]))
        previous = list(map(float, baseline.predict_proba([r[3] for r in rows])[:, 1]))
        result[name] = CandidateComparison.evaluate(rows, current, previous, threshold, prior,
                                                    bootstrap=name == "test_unseen_accounts")
    # Предыдущий эксперимент воспроизводится на каждой контрольной группе численно.
    for name, comparison in result.items():
        previous = old["results"][name]
        for key, actual in comparison["baseline"].items():
            if key == "threshold":
                continue
            expected = previous[key]
            if isinstance(expected, float):
                if abs(actual - expected) > 1e-12:
                    raise ValueError("Контрольные окна/вычисления v1 изменились")
            elif actual != expected:
                raise ValueError("Состав контрольной группы изменился")
    args.weights.parent.mkdir(parents=True, exist_ok=True)
    if code_manifest != source_manifest(root):
        raise ValueError("Код или план изменились во время расчёта; повторите на замороженном дереве")
    candidate.save_model(str(args.weights))
    output = {
        "protocol": "evaluation/RISK-CANDIDATE-V2-PLAN.md", "model": "research-berka-gap-liquidity-v2",
        "test_is_retrospective": True, "production_activated": False, "probability_calibrated": False,
        "source_sha256": source_sha, "baseline_weights_sha256": baseline_sha,
        "candidate_weights_sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "parameters": PARAMETERS, "audit": audit,
        "reproducibility": {**environment, "code_sha256_utf8_lf": code_manifest},
        "training": {"windows": len(train), "positive_windows": sum(r[1] for r in train),
                     "accounts": len({r[2] for r in train}),
                     "positive_accounts": len({r[2] for r in train if r[1]}),
                     "overlapping_windows": True, "account_balanced_weights": True},
        "threshold": threshold, "threshold_candidates": candidates, "results": result,
        "validation_improved": CandidateComparison.improved(selected, result["validation"]["baseline"]),
        "validation_release_policy_passed": CandidateComparison.policy(selected),
        "release": {"allowed": False, "reasons": ["no_target_sme_validation", "test_previously_inspected"]
                    + ([] if CandidateComparison.policy(selected) else ["validation_policy_failed"])},
        "code_sha256_utf8_lf": {str(p.relative_to(root)).replace("\\", "/"):
            hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"validation_improved": output["validation_improved"], "threshold": threshold,
                      "release": output["release"], "unseen": result["test_unseen_accounts"]}), flush=True)


if __name__ == "__main__":
    main()
