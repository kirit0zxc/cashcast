"""Отдельная политика предупреждений: пропуски ограничены до выбора по F2."""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"backend"))

from evaluation.fallback_model.metrics import Score
from evaluation.real_data.risk import metrics
from .model import GapClassifier,ReserveModel
from .run import RiskExperiment

THRESHOLDS=(.01,.02,.03,.05,.075,.1,.15,.2,.25,.3,.4,.5,.6,.7,.8,.9)
METHODS=("current","reserve","geometric","minimum","mean")


class RecallPolicy:
    @staticmethod
    def score(row,method):
        p0,p1=row["scores"]["current"],row["scores"]["reserve4"]
        return {"current":p0,"reserve":p1,"geometric":float(np.sqrt(p0*p1)),
                "minimum":min(p0,p1),"mean":(p0+p1)/2}[method]

    @staticmethod
    def eligible(rows):
        return [r for r in rows if r["opening"]>=0 and r["scores"]["current"] is not None]

    @classmethod
    def evaluate(cls,rows,method,threshold,prior=.01):
        y=[r["label"] for r in rows]
        p=[cls.score(r,method) for r in rows]
        return {**metrics(y,p,threshold,prior),**Score.classification(y,np.asarray(p)>=threshold),
                "method":method,"threshold":threshold,"companies":len({r["company"] for r in rows}),
                "positive_companies":len({r["company"] for r in rows if r["label"]})}

    @classmethod
    def choose(cls,rows,prior=.01):
        base=cls.evaluate(rows,"current",.5,prior)
        minimum_recall=max(.8,base["recall"] or 0.)
        trials=[cls.evaluate(rows,method,threshold,prior) for method in METHODS for threshold in THRESHOLDS]
        feasible=[v for v in trials if v["recall"] is not None and v["recall"]>=minimum_recall and v["fpr"] is not None and v["fpr"]<=.2]
        selected=max(feasible,key=lambda v:(v["f2"] or 0.,-v["fp"],v["threshold"])) if feasible else base
        return {"selected":selected,"baseline":base,"feasible":bool(feasible),"minimum_recall":minimum_recall,"trials":trials}

    @classmethod
    def paired_bootstrap(cls,rows,method,threshold):
        groups=defaultdict(list)
        for row in rows:
            groups[row["company"]].append(row)
        values=list(groups.values())
        changes=defaultdict(list)
        rng=np.random.default_rng(20261024)
        for _ in range(500):
            sampled=[r for index in rng.integers(0,len(values),len(values)) for r in values[index]]
            new,old=cls.evaluate(sampled,method,threshold),cls.evaluate(sampled,"current",.5)
            for metric in ("f2","recall","precision","brier"):
                if new[metric] is not None and old[metric] is not None:
                    changes[metric].append(new[metric]-old[metric])
        return {key:{"valid_resamples":len(values),"ci95_difference":np.quantile(values,[.025,.975]).tolist()} for key,values in changes.items() if values}


class PolicyExperiment:
    @staticmethod
    def run(source,artifacts,output):
        output.mkdir(parents=True,exist_ok=True)
        old=json.loads((artifacts/"results.json").read_text(encoding="utf-8"))
        for name,expected in old["weights_sha256"].items():
            assert hashlib.sha256((artifacts/name).read_bytes()).hexdigest()==expected
        engine=RiskExperiment(source,artifacts)
        from catboost import CatBoostRegressor,CatBoostClassifier
        reserve=ReserveModel(4)
        reserve.model=CatBoostRegressor()
        reserve.model.load_model(str(artifacts/"reserve4.cbm"))
        classifier=GapClassifier()
        classifier.model=CatBoostClassifier()
        classifier.model.load_model(str(artifacts/"classifier.cbm"))
        engine.reserves={"reserve4":reserve}
        engine.classifier=classifier
        engine.prior=old["train"]["constant_prior"]
        rows,_=engine.prepare([date(2026,1,31),date(2026,2,28),date(2026,3,31)],date(2026,4,30))
        rows=engine.predict(rows)
        validation=[{"company":r["snapshot"].account_id,"cutoff":r["snapshot"].as_of.isoformat(),"opening":r["opening"],"label":r["label"],"scores":r["scores"]} for r in rows]
        # Проверяем, что загруженные модели воспроизводят старое выбранное сравнение.
        old_val=old["validation"]["reserve4"]["selected"]
        repeated=RecallPolicy.evaluate(RecallPolicy.eligible(validation),"reserve",old_val["threshold"],engine.prior)
        assert all(repeated[k]==old_val[k] for k in ("tp","fp","fn","tn"))
        read=lambda name:json.loads((artifacts/f"{name}-rows.json").read_text(encoding="utf-8"))
        early=RecallPolicy.eligible(validation+read("calibration")+read("check"))
        decision=RecallPolicy.choose(early,engine.prior)
        selected=decision["selected"]
        report={"selection":decision,"calibrated":False,"production_activated":False,
                "selection_max_fact_date":"2026-07-30","late_periods_previously_seen":True,
                "selected_method":selected["method"],"selected_threshold":selected["threshold"],
                "source_v2_sha256":hashlib.sha256((artifacts/"results.json").read_bytes()).hexdigest()}
        (output/"selection-frozen.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps({"method":selected["method"],"threshold":selected["threshold"],"early_tp":selected["tp"],"early_fp":selected["fp"],"early_fn":selected["fn"]}),flush=True)
        sensitivity=[]
        for cutoff in sorted({r["cutoff"] for r in early}):
            train=[r for r in early if r["cutoff"]!=cutoff]
            excluded=[r for r in early if r["cutoff"]==cutoff]
            choice=RecallPolicy.choose(train,engine.prior)["selected"]
            sensitivity.append({"cutoff":cutoff,"selected":choice["method"],"threshold":choice["threshold"],
                                "scores":RecallPolicy.evaluate(excluded,choice["method"],choice["threshold"],engine.prior)})
        report["leave_one_month_sensitivity_not_forward_test"]=sensitivity
        for name in ("retrospective_development","retrospective_other_companies"):
            rows=RecallPolicy.eligible(read(name))
            report[name]={"candidate":RecallPolicy.evaluate(rows,selected["method"],selected["threshold"],engine.prior),
                          "current":RecallPolicy.evaluate(rows,"current",.5,engine.prior),
                          "paired_company_bootstrap":RecallPolicy.paired_bootstrap(rows,selected["method"],selected["threshold"])}
        report["release_allowed"]=False
        report["release_reason"]="Проверка ретроспективная; единичные положительные компании, независимый контроль отсутствует"
        (output/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--zip",type=Path,required=True)
    parser.add_argument("--artifacts",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    PolicyExperiment.run(args.zip,args.artifacts,args.output)
