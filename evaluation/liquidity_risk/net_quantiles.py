"""Медиана netflow обучается отдельно от математических ожиданий in/out."""

import argparse
import json
import sys
from collections import Counter
from datetime import date,timedelta
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"backend"))

from evaluation.fallback_model.features import DirectCandidate,DirectFeatures
from evaluation.fallback_model.run import Experiment


class NetCandidate:
    def __init__(self,depth,flow_model):
        self.depth=depth
        self.flow_model=flow_model
        self.model=None

    def fit(self,x,y,weights):
        from catboost import CatBoostRegressor
        self.model=CatBoostRegressor(loss_function="MultiQuantile:alpha=0.1,0.5,0.9",iterations=500,
                                    depth=self.depth,learning_rate=.04,l2_leaf_reg=8,random_seed=20261024,
                                    thread_count=4,verbose=False,allow_writing_files=False)
        self.model.fit(x,y,sample_weight=weights)
        return self

    def predict(self,data):
        features,scale,quality=DirectFeatures.make(data)
        quantiles=np.sort(np.asarray(self.model.predict(features)),axis=1)
        values=quantiles[:,1]*scale*np.arange(1,len(features)+1)+data.opening_balance_minor
        if not np.isfinite(values).all() or np.max(abs(values))>9e15:
            raise ValueError("Медианный прогноз выходит за денежный бюджет")
        flows,_,_,_=self.flow_model.predict(data)
        return flows,np.rint(values).astype(np.int64),scale,quality


class NetExperiment(Experiment):
    def train(self):
        from catboost import CatBoostRegressor
        cutoffs,day=[],date(2024,12,31)
        while day+timedelta(days=30)<=date(2025,12,31):
            cutoffs.append(day);day+=timedelta(days=14)
        rows,excluded=self.dataset.windows(cutoffs,date(2025,12,31))
        x,y,owners,scales=[],[],[],[]
        for data,truth,_ in rows:
            features,scale,quality=DirectFeatures.make(data)
            if quality.history_days<28:continue
            horizon=np.arange(1,len(truth)+1)
            net=np.cumsum(truth[:,0]-truth[:,1])
            x.extend(features);y.extend(net/scale/horizon)
            scales.extend(scale*horizon)
            owners.extend([data.account_id]*len(truth))
        x,y=np.asarray(x),np.asarray(y)
        counts=Counter(owners)
        uniform=np.array([len(owners)/len(counts)/counts[owner] for owner in owners])
        money=uniform*np.array(scales)
        money/=money.mean()
        flow=DirectCandidate(6)
        flow.model=CatBoostRegressor()
        flow.model.load_model(str(ROOT/"data/raw/fallback-model-v1/direct_depth6.cbm"))
        self.report["training"]={"rows":len(x),"companies":len(counts),"target_end":"2025-12-31",
                                 "objective":"MultiQuantile netflow, median cash balance", "excluded":excluded}
        for depth in (4,6):
            for kind,weights in (("uniform",uniform),("money",money)):
                name=f"net{depth}_{kind}"
                model=NetCandidate(depth,flow).fit(x,y,weights)
                model.model.save_model(str(self.output/f"{name}.cbm"))
                self.models[name]=model
                print(f"Trained {name}",flush=True)
        self.save()

    def select(self,validation):
        summary=self.summarize(validation)
        base=summary["current"]["30"]
        eligible=[]
        for name,values in summary.items():
            if name in {"current","baseline7"}:continue
            point=values["30"]
            bad=sum(v>1.1*base["cutoff_mae_rub"][k] for k,v in point["cutoff_mae_rub"].items())
            if point["company_macro_mae_rub"]<=base["company_macro_mae_rub"]*1.05 and bad<2:
                eligible.append(name)
        challenger=min(eligible,key=lambda name:summary[name]["30"]["mae_rub"]) if eligible else "current"
        improvement=1-summary[challenger]["30"]["mae_rub"]/base["mae_rub"]
        decision={"selected":challenger if improvement>=.05 else "current","challenger":challenger,
                  "validation_mae_improvement":improvement,"point_validation_gate":improvement>=.05,
                  "selection_source":"validation only, macro and cutoff guardrails","refit_on_test":False}
        self.report["validation"],self.report["selection"]=summary,decision
        (self.output/"selection-frozen.json").write_text(json.dumps(decision,indent=2),encoding="utf-8")
        self.save()
        print(f"Frozen net selection: {decision}",flush=True)
        return decision


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--zip",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    NetExperiment(args.zip,args.output).run()


if __name__=="__main__":
    main()
