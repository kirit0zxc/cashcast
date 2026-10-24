"""Проверка нового минуса на реальных сверенных счетах, без подбора по test."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from statistics import mean, pstdev

from .berka import BerkaDaily
from .models import SEED
from .provenance import manifest


def features(history):
    scale = max(100, mean(d.outgoing for d in history))
    last = history[-1]
    values = [
        last.balance / scale,
        last.date.day,
        last.date.weekday(),
        sum(d.balance < 0 for d in history),
        min(d.balance for d in history) / scale,
    ]
    for attr in ("incoming", "outgoing"):
        for window in (7, 28, 84):
            series = [getattr(d, attr) for d in history[-window:]]
            values.extend((mean(series) / scale, pstdev(series) / scale))
    return values


def metrics(labels, scores, threshold, prior):
    n = len(labels)
    positive = sum(labels)
    tp = sum(y and s >= threshold for y, s in zip(labels, scores, strict=True))
    fp = sum(not y and s >= threshold for y, s in zip(labels, scores, strict=True))
    fn, tn = positive - tp, n - positive - fp
    # Группируем ties: порядок строк не должен улучшать AP/AUC.
    groups = {}
    for y, s in zip(labels, scores, strict=True):
        group = groups.setdefault(float(s), [0, 0])
        group[int(bool(y))] += 1
    auc_sum = negatives_seen = 0
    for score in sorted(groups):
        neg, pos = groups[score]
        auc_sum += pos * (negatives_seen + 0.5 * neg)
        negatives_seen += neg
    ap_sum = seen = pos_seen = 0
    for score in sorted(groups, reverse=True):
        neg, pos = groups[score]
        seen += neg + pos
        pos_seen += pos
        ap_sum += pos * pos_seen / seen
    return {
        "folds": n,
        "positives": positive,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / positive if positive else None,
        "fpr": fp / (fp + tn) if fp + tn else None,
        "f2": 5 * tp / (5 * tp + 4 * fn + fp) if 5 * tp + 4 * fn + fp else 0,
        "roc_auc": auc_sum / (positive * (n - positive)) if 0 < positive < n else None,
        "average_precision": ap_sum / positive if positive else None,
        "brier": mean((s - y) ** 2 for s, y in zip(scores, labels, strict=True))
        if n
        else None,
        "constant_brier": mean((prior - y) ** 2 for y in labels) if n else None,
    }


def build_folds(path):
    groups = {
        name: []
        for name in (
            "train",
            "validation",
            "test_development_accounts",
            "test_unseen_accounts",
        )
    }
    audit = {"accounts": 0, "invalid_days": 0, "excluded_windows": 0}
    for account, days, invalid in BerkaDaily.read(path):
        audit["accounts"] += 1
        audit["invalid_days"] += len(invalid)
        heldout = hashlib.sha256(account.encode()).digest()[0] % 5 == 0
        for i in range(83, len(days) - 30, 30):
            history, future = days[i - 83 : i + 1], days[i + 1 : i + 31]
            if any(d.date in invalid for d in history + future):
                audit["excluded_windows"] += 1
                continue
            if history[-1].balance < 0:
                continue
            if future[-1].date <= date(1996, 12, 31) and not heldout:
                phase = "train"
            elif future[0].date.year == future[-1].date.year == 1997 and not heldout:
                phase = "validation"
            elif future[0].date.year == future[-1].date.year == 1998:
                phase = (
                    "test_unseen_accounts" if heldout else "test_development_accounts"
                )
            else:
                continue
            groups[phase].append(
                (features(history), int(any(d.balance < 0 for d in future)), account)
            )
    return groups, audit


def main():
    from catboost import CatBoostClassifier

    parser = argparse.ArgumentParser()
    parser.add_argument("--berka", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    args = parser.parse_args()
    groups, audit = build_folds(args.berka)
    train = groups["train"]
    fit_accounts = {r[2] for r in train}
    prior = mean(row[1] for row in train)
    if not 0 < prior < 1:
        raise ValueError("В обучении отсутствует один из классов")
    model = CatBoostClassifier(
        iterations=300,
        depth=4,
        learning_rate=0.04,
        loss_function="Logloss",
        random_seed=SEED,
        thread_count=2,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit([r[0] for r in train], [r[1] for r in train])
    predictions = {
        name: list(map(float, model.predict_proba([r[0] for r in rows])[:, 1]))
        for name, rows in groups.items()
        if name != "train"
    }
    labels = [r[1] for r in groups["validation"]]
    candidates = [
        (metrics(labels, predictions["validation"], threshold, prior), threshold)
        for threshold in (0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5)
    ]
    allowed = [
        (m, t) for m, t in candidates if m["fpr"] is not None and m["fpr"] <= 0.1
    ]
    threshold = (
        max(allowed, key=lambda item: (item[0]["f2"], item[1]))[1] if allowed else 1.0
    )
    result = {
        "protocol": "evaluation/REAL-DATA-PLAN.md",
        "model": "research-berka-new-gap-catboost-v1",
        "source_sha256": hashlib.sha256(args.berka.read_bytes()).hexdigest(),
        "audit": audit,
        "train_folds": len(train),
        "train_positives": sum(r[1] for r in train),
        "train_accounts": len(fit_accounts),
        "train_prior": prior,
        "threshold": threshold,
        "validation_threshold_gate_passed": bool(allowed),
        "results": {
            name: {
                **metrics([r[1] for r in groups[name]], scores, threshold, prior),
                "accounts": len({r[2] for r in groups[name]}),
                "actually_seen_in_fit_accounts": len(
                    {r[2] for r in groups[name]} & fit_accounts
                ),
                "positive_accounts": len({r[2] for r in groups[name] if r[1]}),
            }
            for name, scores in predictions.items()
        },
        "production_activated": False,
        "probability_calibrated": False,
        "limitations": [
            "retail_1990s_not_sme",
            "dependent_windows_within_account",
            "unreconciled_windows_excluded",
            "negative_eod_is_proxy_not_unpaid_bill",
        ],
    }
    args.weights.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(args.weights))
    result["reproducibility"] = manifest([args.weights])
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
