"""Три локальных этапа: прежние модели, Chronos, замороженный выбор и отчёт."""
import argparse
import hashlib
import json
import pickle
import time
from datetime import date
from pathlib import Path

import numpy as np

from .specialists import SpecialistMath, SpecialistPolicy
from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.features import DirectCandidate
from evaluation.fallback_model.metrics import Score
from app.modules.forecasting.service import get_forecast_service

PHASES = {
    "validation": ([date(2026,1,31), date(2026,2,28), date(2026,3,31)], date(2026,4,30), False),
    "bridge": ([date(2026,4,30), date(2026,5,31), date(2026,6,30)], date(2026,7,30), False),
    "late_development": ([date(2026,7,31), date(2026,8,31)], date(2026,9,30), False),
    "other_early": ([date(2026,1,31), date(2026,2,28), date(2026,3,31), date(2026,4,30), date(2026,5,31), date(2026,6,30)], date(2026,7,30), True),
    "late_other": ([date(2026,7,31), date(2026,8,31)], date(2026,9,30), True),
}


class FullChronos:
    def __init__(self, output):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)

    def write(self, name, value):
        (self.output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    def load(self, phase, stage="inferred"):
        # Только собственные локальные промежуточные файлы этого эксперимента.
        with (self.output/f"{stage}-{phase}.pickle").open("rb") as stream:
            return pickle.load(stream)

    def save(self, phase, rows, audit, stage):
        with (self.output/f"{stage}-{phase}.pickle").open("wb") as stream:
            pickle.dump({"rows": rows, "audit": audit}, stream)
        self.write(f"{stage}-{phase}-audit.json", audit)

    def prepare(self, source, weights):
        from catboost import CatBoostRegressor
        dataset = Dataset(source)
        candidate = DirectCandidate(6)
        candidate.model = CatBoostRegressor(); candidate.model.load_model(str(weights))
        metadata = {"dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
                    "control_dataset_received": False, "production_activated": False}
        self.write("sources.json", metadata)
        for phase, args in PHASES.items():
            started = time.perf_counter()
            windows, excluded = dataset.windows(*args)
            rows = []
            for i, (snapshot, truth, cohort) in enumerate(windows):
                current = get_forecast_service().run(snapshot)
                base = np.array([[p.inflow_minor, p.outflow_minor, p.balance_p50_minor] for p in current.points])
                interval = np.array([[p.balance_p10_minor, p.balance_p50_minor, p.balance_p90_minor] for p in current.points])
                flows, balance, scale, quality = candidate.predict(snapshot)
                direct = base.copy() if quality.history_days<28 else np.column_stack([flows, balance])
                contexts = SpecialistMath.contexts(snapshot)
                rows.append({"company": snapshot.account_id, "cutoff": snapshot.as_of.isoformat(),
                             "opening": snapshot.opening_balance_minor, "truth": truth, "cohort": cohort,
                             "models": {"current": base, "direct": direct}, "intervals": {"current": interval},
                             "probability": current.risk.probability_any_negative,
                             "daily_probability": [p.probability_negative for p in current.points],
                             "contexts": contexts, "scale": scale if contexts is None else contexts["balance365"][1],
                             "fallback": contexts is None})
                if (i+1)%100==0: print(f"Prepared {phase} {i+1}/{len(windows)}", flush=True)
            self.save(phase, rows, {"windows": len(rows), "excluded": excluded,
                                   "prepare_seconds": time.perf_counter()-started}, "prepared")
            print(f"Prepared {phase}: {len(rows)}", flush=True)

    def infer(self, metadata):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4); torch.manual_seed(20261024)
        model = json.loads(metadata.read_text(encoding="utf-8"))
        pipeline = Chronos2Pipeline.from_pretrained(model["snapshot"], device_map="cpu", local_files_only=True)
        self.write("model.json", model)
        for phase in PHASES:
            data = self.load(phase, "prepared"); rows, audit = data["rows"], data["audit"]
            audit["inference_seconds"] = {}
            for name in ("balance84", "balance365", "flow365"):
                started = time.perf_counter()
                indexes = [i for i, r in enumerate(rows) if not r["fallback"]]
                inputs = [rows[i]["contexts"][name][0].astype(np.float32) for i in indexes]
                if inputs:
                    forecasts, _ = pipeline.predict_quantiles(inputs, prediction_length=30, quantile_levels=[.1,.5,.9],
                                                               batch_size=16, context_length=84 if name=="balance84" else 365,
                                                               cross_learning=False)
                    for i, tensor in zip(indexes, forecasts, strict=True):
                        row = rows[i]; scale = row["contexts"][name][1]
                        raw = tensor.detach().cpu().numpy()
                        shape = (2,30,3) if name=="flow365" else (1,30,3)
                        if raw.shape!=shape or not np.isfinite(raw).all(): raise ValueError("Неверный выход Chronos")
                        values = raw*scale + (0 if name=="flow365" else row["opening"])
                        if np.max(abs(values))>9e15: raise ValueError("Переполнение сумм Chronos")
                        values = np.sort(values, axis=2)
                        if name=="flow365":
                            flows = np.rint(np.maximum(values[:,:,1].T, 0)).astype(np.int64)
                            balance = row["opening"]+np.cumsum(flows[:,0]-flows[:,1])
                            row["models"][name] = np.column_stack([flows, balance])
                        else:
                            row["intervals"][name] = values[0]
                            predicted = row["models"]["current"].copy()
                            predicted[:,2] = np.rint(values[0,:,1]).astype(np.int64)
                            row["models"][name] = predicted
                for row in rows:
                    if row["fallback"]:
                        row["models"][name] = row["models"]["current"].copy()
                        if name!="flow365": row["intervals"][name] = row["intervals"]["current"].copy()
                audit["inference_seconds"][name] = time.perf_counter()-started
            for row in rows:
                for weight in (.25,.5,.75):
                    row["models"][f"blend{int(weight*100)}"] = np.rint(
                        weight*row["models"]["balance365"]+(1-weight)*row["models"]["direct"]).astype(np.int64)
                del row["contexts"]
            audit["fallback_windows"] = sum(r["fallback"] for r in rows)
            self.save(phase, rows, audit, "inferred")
            print(f"Inferred {phase}: {len(rows)}", flush=True)

    @staticmethod
    def summarize(rows):
        result = {}
        names = (*SpecialistPolicy.BALANCES, "flow365", "specialists_separate", "specialists_reconciled")
        for name in names:
            result[name] = {}
            for horizon in (7,14,30):
                score = Score.summarize(rows, name, horizon)
                # Скопированные диагностические потоки не являются прогнозами балансовой модели.
                if name in ("balance84", "balance365", "blend25", "blend50", "blend75"):
                    score.pop("inflow_mae_rub"); score.pop("outflow_mae_rub")
                result[name][str(horizon)] = score
        return result

    def score(self):
        validation = self.load("validation")["rows"]
        policy = SpecialistPolicy.choose(validation)
        self.write("selection-frozen.json", policy)
        early_risk = validation+self.load("bridge")["rows"]
        risk_policy = SpecialistPolicy.choose_risk(early_risk)
        self.write("risk-selection-frozen.json", risk_policy)
        report = {"selection": policy, "risk_selection": risk_policy,
                  "production_activated": False, "release_allowed": False, "independent_control": False,
                  "probability_calibrated": False, "phases": {}}
        for phase in PHASES:
            data = self.load(phase); rows = data["rows"]
            SpecialistPolicy.assemble(rows, policy)
            summary = {"scores": self.summarize(rows), "audit": data["audit"],
                       "paired_ensemble_vs_current": Score.paired_interval(rows, "specialists_separate"),
                       "risk": {n: SpecialistPolicy.risk(rows,n) for n in risk_policy["trials"]},
                       "intervals": {}, "flows": {}, "cash_path_coherence": {}}
            for name in (*SpecialistPolicy.FLOWS,"specialists_separate","specialists_reconciled"):
                summary["flows"][name] = {str(h): {label: SpecialistMath.flow_metrics(rows,name,direction,h)
                    for direction,label in ((0,"inflow"),(1,"outflow"))} for h in (7,14,30)}
            for name in ("specialists_separate","specialists_reconciled"):
                differences = [r["models"][name][:,2]-(r["opening"]+np.cumsum(r["models"][name][:,0]-r["models"][name][:,1])) for r in rows]
                summary["cash_path_coherence"][name] = {
                    "mean_absolute_difference_rub": float(np.mean([abs(d)/100 for d in differences])),
                    "exact_windows": sum(bool(np.all(d==0)) for d in differences),
                    "windows": len(rows), "interpretation": "only if all outputs are treated as one deterministic cash path"}
                if name=="specialists_reconciled": assert all(np.all(d==0) for d in differences)
            for name in ("balance84", "balance365"):
                valid = [r for r in rows if not r["fallback"]]
                for horizon in (7,14,30):
                    coverage = [((r["truth"][:horizon,2]>=r["intervals"][name][:horizon,0]) &
                                 (r["truth"][:horizon,2]<=r["intervals"][name][:horizon,2])).mean() for r in valid]
                    summary["intervals"].setdefault(name,{})[str(horizon)] = {
                        "windows": len(valid), "coverage": float(np.mean(coverage)) if valid else None,
                        "pinball_rub": {str(q): float(np.mean([
                            np.maximum(q*((r["truth"][:horizon,2]-r["intervals"][name][:horizon,j])/100),
                                       (q-1)*((r["truth"][:horizon,2]-r["intervals"][name][:horizon,j])/100)).mean()
                            for r in valid])) if valid else None for j,q in enumerate((.1,.5,.9))},
                        "mean_width_rub": float(np.mean([(r["intervals"][name][:horizon,2]-r["intervals"][name][:horizon,0]).mean()/100 for r in valid])) if valid else None}
                risk_rows = [r for r in valid if r["opening"]>=0 and r["probability"] is not None]
                summary["risk"][name]["ranking"] = SpecialistMath.rank_metrics(
                    [np.any(r["truth"][:,2]<0) for r in risk_rows],
                    [-np.min(r["intervals"][name][:,0])/r["scale"] for r in risk_rows])
                summary["risk"][name]["ranking"]["windows_without_fallback"] = len(risk_rows)
                summary["risk"][name]["ranking"]["current_on_same_windows"] = SpecialistMath.rank_metrics(
                    [np.any(r["truth"][:,2]<0) for r in risk_rows], [r["probability"] for r in risk_rows])
                summary["risk"][name]["ranking"]["current_on_same_windows"]["score_semantics"] = "current bootstrap probability, not calibrated"
            report["phases"][phase] = summary
            self.write("results.json", report)
            print(f"Scored {phase}; balance={policy['balance']}, in={policy['inflow']}, out={policy['outflow']}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("prepare","infer","score"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--model-info", type=Path)
    args = parser.parse_args(); runner = FullChronos(args.output)
    if args.stage=="prepare": runner.prepare(args.zip,args.weights)
    elif args.stage=="infer": runner.infer(args.model_info)
    else: runner.score()


if __name__=="__main__": main()
