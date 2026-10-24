"""Ранний выбор checkpoint, затем неизменная проверка переноса на остальные фазы."""
import argparse
import gc
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

from .finetune import FineTune
from evaluation.fallback_model.metrics import Score


class FineTuneEvaluation:
    MODELS = ("balance365", "ft100", "ft300")
    PHASES = ("validation", "bridge", "late_development", "other_early", "late_other")

    def __init__(self, training, cache, output):
        self.training, self.cache, self.output = training, cache, output
        output.mkdir(parents=True, exist_ok=True)
        if not (training/"training-completed.json").exists():
            raise RuntimeError("Обучение ещё не подтверждено завершённым")

    @staticmethod
    def read_pickle(path):
        # Исключительно доверенные собственные артефакты локальных запусков.
        with path.open("rb") as stream:
            return pickle.load(stream)

    def infer(self, phases):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4)
        torch.manual_seed(20261025)
        rows_by_phase = {p:self.read_pickle(self.cache/f"inferred-{p}.pickle")["rows"] for p in phases}
        for name, step in (("ft100",100),("ft300",300)):
            checkpoint = self.training/f"checkpoint-{step}"
            pipeline = Chronos2Pipeline.from_pretrained(str(checkpoint), device_map="cpu", local_files_only=True)
            for phase, rows in rows_by_phase.items():
                prepared = self.read_pickle(self.cache/f"prepared-{phase}.pickle")["rows"]
                identities = lambda values: [(r["company"],r["cutoff"]) for r in values]
                if identities(rows) != identities(prepared):
                    raise ValueError("Разошлись исходные окна")
                indexes = [i for i,r in enumerate(prepared) if not r["fallback"]]
                inputs = [prepared[i]["contexts"]["balance365"][0].astype(np.float32) for i in indexes]
                forecasts, _ = pipeline.predict_quantiles(inputs, prediction_length=30, quantile_levels=[.1,.5,.9],
                                                   context_length=365, batch_size=16, cross_learning=False)
                for i,tensor in zip(indexes,forecasts,strict=True):
                    row = rows[i]
                    values = tensor.detach().cpu().numpy()[0]*prepared[i]["contexts"]["balance365"][1]+row["opening"]
                    if values.shape != (30,3) or not np.isfinite(values).all() or np.max(abs(values))>9e15:
                        raise ValueError("Неверный прогноз дообученной модели")
                    values = np.sort(values,axis=1)
                    row["intervals"][name] = values
                    row["models"][name] = row["models"]["current"].copy()
                    row["models"][name][:,2] = np.rint(values[:,1]).astype(np.int64)
                for row in rows:
                    if row["fallback"]:
                        row["models"][name] = row["models"]["current"].copy()
                        row["intervals"][name] = row["intervals"]["current"].copy()
                print(f"Inferred {name}: {phase} ({len(rows)} windows)", flush=True)
            del pipeline
            gc.collect()
        for phase,rows in rows_by_phase.items():
            with (self.output/f"inferred-{phase}.pickle").open("wb") as stream:
                pickle.dump(rows,stream)
        return rows_by_phase

    @staticmethod
    def risk(rows, name):
        valid = [r for r in rows if r["opening"]>=0 and r["probability"] is not None]
        labels = [bool(np.any(r["truth"][:,2]<0)) for r in valid]
        flags = [r["probability"]>=.5 if name=="current" or r["fallback"] else
                 bool(np.any(r["intervals"][name][:,0]<0)) for r in valid]
        result = Score.classification(labels,flags)
        result["fpr"] = result["fp"]/(result["fp"]+result["tn"]) if result["fp"]+result["tn"] else None
        result["positive_companies"] = len({r["company"] for r,y in zip(valid,labels) if y})
        return result

    @classmethod
    def choose(cls, validation, early):
        scores = {n:{str(h):Score.summarize(validation,n,h) for h in (7,14,30)} for n in cls.MODELS}
        base = scores["balance365"]
        eligible = [n for n in cls.MODELS if all(scores[n][str(h)]["rmse_rub"]<=base[str(h)]["rmse_rub"]*1.05 for h in (7,14,30))]
        selected = min(eligible,key=lambda n:(sum(scores[n][str(h)]["mae_rub"]/base[str(h)]["mae_rub"] for h in (7,14,30)),n!="balance365"))
        risks = {n:cls.risk(early,n) for n in ("current",*cls.MODELS)}
        base_risk = risks["current"]
        allowed = [n for n,v in risks.items() if base_risk["positives"]>=5 and v["tp"]>=base_risk["tp"] and v["fp"]<=base_risk["fp"]]
        risk = min(allowed,key=lambda n:(risks[n]["fp"],risks[n]["fn"],n!="current",n)) if allowed else "current"
        return {"point":selected,"risk":risk,"point_trials":scores,"risk_trials":risks,
                "point_selection":"development January-March", "risk_selection":"development January-June"}

    @classmethod
    def summarize(cls, rows):
        scores = {}
        for name in ("current","blend75",*cls.MODELS):
            scores[name] = {}
            for horizon in (7,14,30):
                score = Score.summarize(rows,name,horizon)
                # Балансовые модели не обучались прогнозировать скопированные потоки.
                score.pop("inflow_mae_rub"); score.pop("outflow_mae_rub")
                if name in rows[0]["intervals"]:
                    intervals = np.stack([r["intervals"][name][:horizon] for r in rows])/100
                    truth = np.stack([r["truth"][:horizon,2] for r in rows])/100
                    residual = truth[:,:,None]-intervals
                    quantiles = np.array([.1,.5,.9])
                    score["pinball_rub"] = float(np.maximum(quantiles*residual,(quantiles-1)*residual).mean())
                    score["p10_p90_coverage"] = float(((truth>=intervals[:,:,0]) & (truth<=intervals[:,:,2])).mean())
                scores[name][str(horizon)] = score
        return {"scores":scores,"risk":{n:cls.risk(rows,n) for n in ("current",*cls.MODELS)},
                "fallback_windows":sum(r["fallback"] for r in rows)}

    def run(self):
        early = self.infer(("validation","bridge"))
        policy = self.choose(early["validation"],early["validation"]+early["bridge"])
        FineTune.write(self.output/"selection-frozen.json",policy)
        print(f"Frozen selection: point={policy['point']}, risk={policy['risk']}",flush=True)
        report = {"selection":policy,"phases":{},"independent_control":False,"production_activated":False,
                  "probability_calibrated":False,"release_allowed":False}
        for phase,rows in early.items():
            report["phases"][phase] = self.summarize(rows)
        FineTune.write(self.output/"results.json",report)
        later = self.infer(self.PHASES[2:])
        for phase,rows in later.items():
            report["phases"][phase] = self.summarize(rows)
        report["weights"] = {name:FineTune.fingerprints(self.training/f"checkpoint-{step}") for name,step in (("ft100",100),("ft300",300))}
        report["cache_sources"] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.cache.glob("inferred-*.pickle")}
        FineTune.write(self.output/"results.json",report)
        print("Fine-tuning evaluation completed",flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--training",type=Path,default=Path("data/raw/chronos-finetune-v13"))
    parser.add_argument("--cache",type=Path,default=Path("data/raw/chronos-specialists-v8"))
    parser.add_argument("--output",type=Path,default=Path("data/raw/chronos-finetune-v13/evaluation"))
    args = parser.parse_args()
    FineTuneEvaluation(args.training,args.cache,args.output).run()
