"""Предупреждения по нижнему квантилю; вероятность горизонта не изобретается."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"backend"))

from app.modules.forecasting.service import get_forecast_service
from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from .chronos_trial import BalanceContext

QUANTILES=(.1,.2,.3,.4,.5)


class QuantileWarning:
    @staticmethod
    def triggered(values):
        return bool(np.min(values)<0)

    @staticmethod
    def summarize(rows,q):
        rows=[r for r in rows if r["opening"]>=0 and r["current_probability"] is not None]
        y=[r["label"] for r in rows]
        p=[r["warnings"][str(q)] for r in rows]
        result=Score.classification(y,p)
        result["fpr"]=result["fp"]/(result["fp"]+result["tn"]) if result["fp"]+result["tn"] else None
        result["quantile"]=q
        result["probability"]=None
        return result


class WarningExperiment:
    def __init__(self,source,metadata,output):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4);torch.manual_seed(20261024)
        model=json.loads(metadata.read_text(encoding="utf-8"))
        self.pipeline=Chronos2Pipeline.from_pretrained(model["snapshot"],device_map="cpu",local_files_only=True)
        self.dataset=Dataset(source)
        self.output=output;output.mkdir(parents=True,exist_ok=True)
        self.report={"model_revision":model["revision"],"production_activated":False,"probability":None,
                     "warning_semantics":"lower daily quantile crosses zero","late_periods_previously_seen":True}

    def collect(self,cutoffs,limit,heldout=False):
        windows,excluded=self.dataset.windows(cutoffs,limit,heldout)
        rows,inputs,locations=[],[],[]
        for data,truth,_ in windows:
            baseline=get_forecast_service().run(data)
            p=baseline.risk.probability_any_negative
            row={"company":data.account_id,"cutoff":data.as_of.isoformat(),"opening":data.opening_balance_minor,
                 "current_probability":p,"label":bool(np.any(truth[:,2]<0)),"warnings":{},"fallback":False}
            context=BalanceContext.make(data)
            if context is None:
                row["warnings"]={str(q):bool(p>=.5) if p is not None else False for q in QUANTILES}
                row["fallback"]=True
            else:
                series,scale=context
                row["scale"]=scale
                locations.append(len(rows));inputs.append(series.astype(np.float32)[None,:])
            rows.append(row)
        if inputs:
            forecasts,_=self.pipeline.predict_quantiles(inputs,prediction_length=30,quantile_levels=list(QUANTILES),
                                                        batch_size=16,context_length=365,cross_learning=False)
            for index,tensor in zip(locations,forecasts,strict=True):
                row=rows[index]
                values=np.sort(tensor.numpy()[0],axis=1)*row["scale"]+row["opening"]
                row["warnings"]={str(q):QuantileWarning.triggered(values[:,i]) for i,q in enumerate(QUANTILES)}
        return rows,excluded

    def run(self):
        early,excluded=self.collect([date(2026,1,31),date(2026,2,28),date(2026,3,31),date(2026,4,30),date(2026,5,31),date(2026,6,30)],date(2026,7,30))
        trials=[QuantileWarning.summarize(early,q) for q in QUANTILES]
        feasible=[v for v in trials if v["recall"]==1 and v["fpr"] is not None and v["fpr"]<=.25]
        choice=min(feasible,key=lambda v:(v["fp"],-v["quantile"])) if feasible else None
        self.report["selection"]={"trials":trials,"selected":choice,"feasible":bool(feasible),"excluded":excluded}
        (self.output/"selection-frozen.json").write_text(json.dumps(self.report,indent=2),encoding="utf-8")
        # При непрохождении сохраняем q=.1как заранее названную диагностику, не выбранную модель.
        q=choice["quantile"] if choice else .1
        print(f"Frozen warning quantile={q}, feasible={bool(feasible)}",flush=True)
        for name,heldout in (("retrospective_development",False),("retrospective_other_companies",True)):
            rows,excluded=self.collect([date(2026,7,31),date(2026,8,31)],date(2026,9,30),heldout)
            valid=[r for r in rows if r["opening"]>=0 and r["current_probability"] is not None]
            baseline=Score.classification([r["label"] for r in valid],[r["current_probability"]>=.5 for r in valid])
            self.report[name]={"candidate":QuantileWarning.summarize(rows,q),"current":baseline,"excluded":excluded}
            (self.output/f"{name}-rows.json").write_text(json.dumps(rows),encoding="utf-8")
            print(f"Completed warning {name}",flush=True)
        self.report["release_allowed"]=False
        (self.output/"results.json").write_text(json.dumps(self.report,indent=2),encoding="utf-8")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--zip",type=Path,required=True)
    parser.add_argument("--model-info",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    WarningExperiment(args.zip,args.model_info,args.output).run()
