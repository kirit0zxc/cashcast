"""Причинные входы, согласование сумм и выбор специалистов по ранним данным."""
from collections import defaultdict
from datetime import timedelta

import numpy as np

from .chronos_trial import BalanceContext
from evaluation.fallback_model.metrics import Score


class SpecialistMath:
    @staticmethod
    def contexts(data):
        context = BalanceContext.make(data)
        if context is None:
            return None
        balances, scale = context
        start = data.as_of - timedelta(days=len(balances)-1)
        flows = np.zeros((len(balances), 2))
        for txn in data.txns:
            if txn.account_id == data.account_id and start <= txn.booked_on <= data.as_of:
                flows[(txn.booked_on-start).days, 0 if txn.direction == "in" else 1] += txn.amount_minor
        short = flows[-84:]
        short_scale = max(100., float(short.sum()/len(short)))
        return {"balance365": (balances[None, :], scale),
                "balance84": ((balances[-84:]*scale/short_scale)[None, :], short_scale),
                "flow365": (flows.T/scale, scale)}

    @staticmethod
    def reconcile(flows, balances, opening):
        flows, balances = np.asarray(flows), np.asarray(balances)
        if flows.shape != (len(balances), 2) or not np.isfinite(flows).all() or not np.isfinite(balances).all():
            raise ValueError("Непригодные суммы для согласования")
        if np.max(abs(flows), initial=0)>9e15 or np.max(abs(balances), initial=0)>9e15 or abs(opening)>9e15:
            raise ValueError("Слишком большие суммы для согласования")
        target = np.rint(balances).astype(np.int64)
        delta = np.diff(target, prepend=int(opening))
        incoming = np.maximum.reduce([np.zeros(len(delta)), delta.astype(float),
                                      (flows[:, 0]+flows[:, 1]+delta)/2])
        incoming = np.rint(incoming).astype(np.int64)
        outgoing = incoming-delta
        assert np.all(incoming>=0) and np.all(outgoing>=0)
        return np.column_stack([incoming, outgoing, target])

    @staticmethod
    def rank_metrics(labels, scores):
        # Только ранжирование: произвольный score не выдаём за вероятность.
        groups = defaultdict(lambda: [0, 0])
        for y, score in zip(labels, scores, strict=True):
            if not np.isfinite(score): raise ValueError("Нечисловой score")
            groups[float(score)][int(bool(y))] += 1
        positive = sum(v[1] for v in groups.values()); negative = sum(v[0] for v in groups.values())
        wins = seen_neg = 0
        for score in sorted(groups):
            neg, pos = groups[score]; wins += pos*(seen_neg+.5*neg); seen_neg += neg
        ap = seen = seen_pos = 0
        for score in sorted(groups, reverse=True):
            neg, pos = groups[score]; seen += neg+pos; seen_pos += pos; ap += pos*seen_pos/seen
        return {"roc_auc": wins/(positive*negative) if positive and negative else None,
                "average_precision": ap/positive if positive else None,
                "probability": None, "score_semantics": "negative minimum p10 divided by historical flow scale"}

    @staticmethod
    def flow_metrics(rows, name, direction, horizon=30):
        errors = [r["models"][name][:horizon, direction]-r["truth"][:horizon, direction] for r in rows]
        return {"mae_rub": float(np.mean([abs(e)/100 for e in errors])),
                "total_mae_rub": float(np.mean([abs(e.sum())/100 for e in errors])),
                "rmse_rub": float(np.sqrt(np.mean([(e/100.)**2 for e in errors])))}


class SpecialistPolicy:
    BALANCES = ("current", "direct", "balance84", "balance365", "blend25", "blend50", "blend75")
    FLOWS = ("current", "direct", "flow365")

    @classmethod
    def choose(cls, rows):
        if not rows: raise ValueError("Нет ранних данных для выбора")
        scores = {name: Score.summarize(rows, name) for name in cls.BALANCES}
        base = scores["current"]
        eligible = [name for name, score in scores.items()
                    if score["rmse_rub"]<=base["rmse_rub"]*1.05
                    and score["company_macro_mae_rub"]<=base["company_macro_mae_rub"]*1.05]
        balance = min(eligible, key=lambda n: (scores[n]["mae_rub"], n))
        flow_choices, flow_trials = [], []
        for direction in (0, 1):
            metrics = {n: SpecialistMath.flow_metrics(rows, n, direction) for n in cls.FLOWS}
            allowed = [n for n in cls.FLOWS if metrics[n]["total_mae_rub"]<=metrics["current"]["total_mae_rub"]*1.05]
            flow_choices.append(min(allowed, key=lambda n: (metrics[n]["mae_rub"], n)))
            flow_trials.append(metrics)
        return {"balance": balance, "inflow": flow_choices[0], "outflow": flow_choices[1],
                "balance_trials": scores, "flow_trials": flow_trials, "selection": "development January-March only"}

    @staticmethod
    def assemble(rows, policy):
        for row in rows:
            balances = row["models"][policy["balance"]][:, 2]
            flows = np.column_stack([row["models"][policy["inflow"]][:, 0], row["models"][policy["outflow"]][:, 1]])
            row["models"]["specialists_separate"] = np.column_stack([flows, balances])
            row["models"]["specialists_reconciled"] = SpecialistMath.reconcile(flows, balances, row["opening"])

    @staticmethod
    def risk(rows, policy, horizon=30):
        if horizon != 30:
            raise ValueError("Общая текущая вероятность измерена только для 30 дней")
        valid = [r for r in rows if r["opening"]>=0 and r["probability"] is not None]
        labels, flags = [], []
        for row in valid:
            labels.append(bool(np.any(row["truth"][:horizon, 2]<0)))
            # Общая текущая вероятность известна только для полного горизонта.
            current = row["probability"]>=.5
            c84 = bool(np.any(row["intervals"]["balance84"][:horizon, 0]<0))
            c365 = bool(np.any(row["intervals"]["balance365"][:horizon, 0]<0))
            if row["fallback"]: c84 = c365 = current
            flags.append({"current": current, "balance84": c84, "balance365": c365,
                          "union": current or c365, "intersection": current and c365}[policy])
        result = Score.classification(labels, flags)
        result["fpr"] = result["fp"]/(result["fp"]+result["tn"]) if result["fp"]+result["tn"] else None
        result["positive_companies"] = len({r["company"] for r, y in zip(valid, labels) if y})
        result["fallback_windows"] = sum(r["fallback"] for r in valid)
        return result

    @classmethod
    def choose_risk(cls, rows):
        trials = {name: cls.risk(rows, name) for name in ("current", "balance84", "balance365", "union", "intersection")}
        base = trials["current"]
        eligible = [name for name, score in trials.items() if base["positives"]>=5
                    and score["recall"]>=base["recall"] and score["fpr"]<=base["fpr"]]
        choice = min(eligible, key=lambda n: (trials[n]["fp"], trials[n]["fn"], n)) if eligible else "current"
        return {"selected": choice, "trials": trials, "selection": "development January-June only"}
