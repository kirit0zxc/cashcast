"""Однопараметрическая настройка масштаба риска с неизменными предупреждениями."""

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
from evaluation.real_data.risk import metrics


class RiskScale:
    def __init__(self,intercept):
        self.intercept=float(intercept)

    def predict(self,p):
        p=np.clip(np.asarray(p,dtype=float),.0025,.9975)
        logits=np.log(p/(1-p))+self.intercept
        return 1/(1+np.exp(-logits))

    @classmethod
    def fit(cls,p,y):
        target=(sum(y)+.5)/(len(y)+1)
        left,right=-30.,30.
        for _ in range(100):
            middle=(left+right)/2
            if np.mean(cls(middle).predict(p))>target:right=middle
            else:left=middle
        return cls((left+right)/2),target


class ScaleExperiment:
    @staticmethod
    def collect(dataset,cutoffs,limit):
        windows,_=dataset.windows(cutoffs,limit)
        rows=[]
        for data,truth,_ in windows:
            result=get_forecast_service().run(data)
            if data.opening_balance_minor<0 or result.risk.probability_any_negative is None:continue
            rows.append({"company":data.account_id,"p":result.risk.probability_any_negative,"y":bool(np.any(truth[:,2]<0))})
        return rows

    @staticmethod
    def evaluate(rows,scale,prior):
        y=[r["y"] for r in rows]
        p=[r["p"] for r in rows]
        updated=scale.predict(p)
        threshold=float(scale.predict(.5))
        assert np.array_equal(np.asarray(p)>=.5,updated>=threshold)
        def summarize(scores,threshold):
            base={**metrics(y,scores,threshold,prior),**Score.classification(y,np.asarray(scores)>=threshold)}
            clipped=np.clip(scores,1e-12,1-1e-12)
            labels=np.asarray(y,dtype=float)
            base["log_loss"]=float(np.mean(-labels*np.log(clipped)-(1-labels)*np.log(1-clipped)))
            return base
        raw,new=summarize(p,.5),summarize(updated.tolist(),threshold)
        assert raw["roc_auc"]==new["roc_auc"]
        return {"raw":raw,"scaled":new,"threshold":threshold,"alerts_preserved":True}

    @classmethod
    def run(cls,source,risk_artifacts,output):
        output.mkdir(parents=True,exist_ok=True)
        data=Dataset(source)
        rows=cls.collect(data,[date(2026,1,31),date(2026,2,28),date(2026,3,31)],date(2026,4,30))
        def read(name):
            raw=json.loads((risk_artifacts/f"{name}-rows.json").read_text())
            return [{"company":r["company"],"p":r["scores"]["current"],"y":bool(r["label"])}
                    for r in raw if r["opening"]>=0 and r["scores"]["current"] is not None]
        rows+=read("calibration")+read("check")
        scale,prior=RiskScale.fit([r["p"] for r in rows],[r["y"] for r in rows])
        report={"intercept":scale.intercept,"fit_prior":prior,"fit_windows":len(rows),"fit_positives":sum(r["y"] for r in rows),
                "scope":"new negative EOD within30days; separate horizon-only estimator",
                "calibrated":False,"production_activated":False,"control_dataset_used":False,
                "retrospective_periods_previously_seen":True,"fit_max_fact_date":"2026-07-30"}
        (output/"calibrator-frozen.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        for name in ("retrospective_development","retrospective_other_companies"):
            report[name]=cls.evaluate(read(name),scale,prior)
        (output/"results.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps({"intercept":scale.intercept,"windows":len(rows),"positives":report["fit_positives"]}),flush=True)
        return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--zip",type=Path,required=True)
    parser.add_argument("--risk-artifacts",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    ScaleExperiment.run(args.zip,args.risk_artifacts,args.output)
