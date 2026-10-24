"""Независимый zero-shot ориентир; история не покидает локальный компьютер."""

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"backend"))

from app.modules.forecasting.service import get_forecast_service
from app.modules.forecasting.v2.quality import assess_quality,validate_input
from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score


class BalanceContext:
    @staticmethod
    def make(snapshot):
        data=validate_input(snapshot)
        quality=assess_quality(data,lookback_days=365)
        if quality.history_days<28 or not quality.eligible_for_simulation:
            return None
        daily=defaultdict(int)
        gross=0
        for txn in data.txns:
            if quality.training_start<=txn.booked_on<=data.as_of:
                daily[txn.booked_on]+=txn.amount_minor*(1 if txn.direction=="in" else -1)
                gross+=txn.amount_minor
        days=[quality.training_start+timedelta(days=i) for i in range(quality.history_days)]
        # От текущего подтверждённого остатка идём назад по причинным потокам.
        net=np.array([daily[day] for day in days],dtype=np.int64)
        balances=data.opening_balance_minor-net.sum()+np.cumsum(net)
        observed={b.balance_date:b.closing_balance_minor for b in data.daily_balances}
        for day,value in zip(days,balances):
            if day in observed and observed[day]!=value:
                raise ValueError("Контекст Chronos не согласован с историческими остатками")
        scale=max(100.,gross/len(days))
        return (balances.astype(float)-data.opening_balance_minor)/scale,scale


class ChronosExperiment:
    def __init__(self,source,model_info,output):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4)
        torch.manual_seed(20261024)
        self.metadata=json.loads(model_info.read_text(encoding="utf-8"))
        self.pipeline=Chronos2Pipeline.from_pretrained(self.metadata["snapshot"],device_map="cpu",local_files_only=True)
        self.dataset=Dataset(source)
        self.output=output
        output.mkdir(parents=True,exist_ok=True)
        self.report={"model":self.metadata,"torch":torch.__version__,"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
                     "production_activated":False,"zero_shot":True,"cross_learning":False,"calibrated":False,
                     "unseen_control":False,"context_days":365,"batch_size":16}

    def evaluate(self,dates,limit,heldout=False):
        windows,excluded=self.dataset.windows(dates,limit,heldout)
        rows,inputs,locations=[],[],[]
        for snapshot,truth,cohort in windows:
            current=get_forecast_service().run(snapshot)
            base=np.array([[p.inflow_minor,p.outflow_minor,p.balance_p50_minor] for p in current.points])
            row={"company":snapshot.account_id,"cutoff":snapshot.as_of.isoformat(),"opening":snapshot.opening_balance_minor,
                 "truth":truth,"cohort":cohort,"models":{"current":base},"fallback":False}
            context=BalanceContext.make(snapshot)
            if context is None:
                row["models"]["chronos"]=base.copy()
                row["fallback"]=True
            else:
                series,scale=context
                row["scale"]=scale
                inputs.append(series.astype(np.float32)[None,:]);locations.append(len(rows))
            rows.append(row)
        started=time.perf_counter()
        if inputs:
            quantiles,_=self.pipeline.predict_quantiles(inputs,prediction_length=30,quantile_levels=[.1,.5,.9],
                                                        batch_size=16,context_length=365,cross_learning=False)
            for index,tensor in zip(locations,quantiles,strict=True):
                row=rows[index]
                values=tensor.detach().cpu().numpy()[0]*row["scale"]+row["opening"]
                if values.shape!=(30,3) or not np.isfinite(values).all() or np.max(abs(values))>9e15:
                    raise ValueError("Непригодный выход Chronos")
                values=np.sort(values,axis=1)
                output=row["models"]["current"].copy()
                output[:,2]=np.rint(values[:,1]).astype(np.int64)
                row["models"]["chronos"]=output
                row["coverage"]=float(np.mean((row["truth"][:,2]>=values[:,0]) & (row["truth"][:,2]<=values[:,2])))
        for row in rows:
            for weight in (.25,.5,.75):
                row["models"][f"chronos_blend{weight}"]=np.rint(weight*row["models"]["chronos"]+(1-weight)*row["models"]["current"]).astype(np.int64)
        return rows,{"excluded":excluded,"fallback_windows":sum(r["fallback"] for r in rows),
                     "inference_seconds":time.perf_counter()-started,
                     "interval_coverage":float(np.mean([r["coverage"] for r in rows if "coverage" in r])) if inputs else None}

    @staticmethod
    def summarize(rows):
        return {name:{str(h):Score.summarize(rows,name,h) for h in (7,14,30)} for name in rows[0]["models"]}

    def save(self):
        (self.output/"results.json").write_text(json.dumps(self.report,ensure_ascii=False,indent=2),encoding="utf-8")

    def run(self):
        rows,audit=self.evaluate([date(2026,1,31),date(2026,2,28),date(2026,3,31)],date(2026,4,30))
        summary=self.summarize(rows)
        base=summary["current"]["30"]
        eligible=[name for name,values in summary.items() if name!="current" and values["30"]["company_macro_mae_rub"]<=base["company_macro_mae_rub"]*1.05]
        challenger=min(eligible,key=lambda name:summary[name]["30"]["mae_rub"]) if eligible else "current"
        improvement=1-summary[challenger]["30"]["mae_rub"]/base["mae_rub"]
        self.report["validation"]={"scores":summary,"audit":audit}
        self.report["selection"]={"challenger":challenger,"selected":challenger if improvement>=.05 else "current",
                                  "validation_mae_improvement":improvement,"validation_gate":improvement>=.05}
        (self.output/"selection-frozen.json").write_text(json.dumps(self.report["selection"],indent=2),encoding="utf-8")
        self.save();print(f"Frozen Chronos selection: {self.report['selection']}",flush=True)
        for name,heldout in (("retrospective_development",False),("retrospective_other_companies",True)):
            rows,audit=self.evaluate([date(2026,7,31),date(2026,8,31)],date(2026,9,30),heldout)
            self.report[name]={"scores":self.summarize(rows),"audit":audit,
                               "paired_challenger_vs_current":Score.paired_interval(rows,challenger)}
            self.save();print(f"Finished Chronos {name}",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--zip",type=Path,required=True)
    parser.add_argument("--model-info",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    ChronosExperiment(args.zip,args.model_info,args.output).run()
