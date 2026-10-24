"""Исследовательский backtest: исходные цели и причинная маска истории."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
import lightgbm as lgb

from evaluation.model_compare.organizers import load, build, train_for, VALIDATION, HOLDOUT
from evaluation.model_compare.features import base, scale, _paths, regression_matrix, regression_targets
from evaluation.model_compare.models import GlobalLightGBM, ProductModel, CURRENT, REFERENCE, REGRESSOR

OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / "data/raw/quality-20261025/benchmark"


def uncertainty_intervals(transactions, balances):
    """Несверка становится известна только в день второго наблюдаемого остатка."""
    result = {}
    for company, txns in transactions.items():
        net = defaultdict(int)
        for t in txns:
            net[t.booked_on] += t.amount_minor * (1 if t.direction.value == "in" else -1)
        days = sorted(balances[company])
        bad = []
        for left, right in zip(days, days[1:]):
            # Остатки есть на каждом дне с операциями; суммируем интервал явно.
            delta = sum(net.get(left + timedelta(days=k), 0) for k in range(1, (right-left).days+1))
            if balances[company][right] - balances[company][left] != delta:
                bad.append((left, right))
        result[company] = bad
    return result


def cleaned(window, intervals):
    inc, out, bal = window.inc.copy(), window.out.copy(), window.bal.copy()
    start = window.as_of - timedelta(days=len(inc)-1)
    for left, right in intervals:
        if right > window.as_of or right < start:
            continue
        a = max(0, (left-start).days+1)
        b = min(len(inc), (right-start).days+1)
        inc[a:b], out[a:b] = np.nan, np.nan
        # Сам наблюдаемый EOD не подменяем; неизвестен только перенос внутри разрыва.
        bal[a:max(a,b-1)] = np.nan
    return replace(window, inc=inc, out=out, bal=bal)


def point_features(w):
    s = scale(w)
    paths = _paths(w)
    return np.r_[base(w,s), w.as_of.month, w.as_of.weekday(),
                 np.isnan(w.inc).sum(), np.isnan(w.bal).sum(),
                 paths["month"]/s, paths["two_months"]/s,
                 paths["weekday"]/s, paths["recurring"]/s]


def seasonal(w, period):
    net = np.nan_to_num(w.inc-w.out)
    path = np.resize(net[-period:], 30)
    return w.opening + np.cumsum(path)


def weekday(w):
    past = [(w.as_of-timedelta(days=83-k)).weekday() for k in range(84)]
    net = w.inc-w.out
    values = []
    for h in range(1,31):
        selected = net[np.array(past) == (w.as_of+timedelta(days=h)).weekday()]
        selected = selected[np.isfinite(selected)]
        values.append(float(selected.mean()) if len(selected) else 0.)
    return w.opening + np.cumsum(values)


def confusion(y,p):
    return {"tp":int((y&p).sum()), "fp":int((~y&p).sum()),
            "fn":int((y&~p).sum()), "tn":int((~y&~p).sum())}


def metrics(y,p,opening,lo=None,hi=None):
    e=(p-y)/100
    mask=opening>=0
    result={"windows":len(y),"days":int(y.size),"mae_rub":float(np.abs(e).mean()),
            "rmse_rub":float(np.sqrt(np.mean(e*e))),"bias_rub":float(e.mean()),
            "mae30_rub":float(np.abs(e[:,-1]).mean()),
            "wape":float(np.abs(p-y).sum()/np.abs(y).sum()),
            "mae_by_day_rub":np.abs(e).mean(axis=0).tolist(),
            "daily_negative":confusion(y<0,p<0),
            "new_gap":confusion((y[mask]<0).any(axis=1),(p[mask]<0).any(axis=1)),
            "new_gap_windows":int(mask.sum())}
    if lo is not None:
        result["coverage_p10_p90"]=float(((lo<=y)&(y<=hi)).mean())
    return result


def bootstrap(delta, companies):
    groups=np.unique(companies)
    sums=np.array([delta[companies==c].sum() for c in groups])
    counts=np.array([(companies==c).sum() for c in groups])
    rng=np.random.default_rng(42)
    draws=rng.integers(0,len(groups),(2000,len(groups)))
    vals=sums[draws].sum(axis=1)/counts[draws].sum(axis=1)
    return {"difference_mae_rub":float(delta.mean()),"ci95_rub":np.quantile(vals,[.025,.975]).tolist(),
            "unit":"company","repetitions":2000,"companies":len(groups),
            "companies_improved":int((sums<0).sum())}


def save_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")


def source_hashes():
    paths=[Path(__file__),OUT/"EXPERIMENT-PLAN.md",*sorted((ROOT/"evaluation/model_compare").glob("*.py")),
           ROOT/"evaluation/backtest.py",ROOT/"backend/app/modules/contracts.py"]
    paths += sorted(p for p in (ROOT/"backend/app/modules/forecasting").rglob("*.py") if p.name!="snapshot.py")
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--zip",required=True,type=Path)
    args=parser.parse_args()
    started=time.time()
    def log(msg): print(f"[{time.time()-started:.1f}s] {msg}",flush=True)
    PRIVATE.mkdir(parents=True,exist_ok=True)
    initial_hashes=source_hashes()
    transactions,balances=load(args.zip)
    intervals=uncertainty_intervals(transactions,balances)
    log(f"loaded {len(transactions)} companies; {sum(map(len,intervals.values()))} historical discrepancies")
    train,control,skipped=build(transactions,balances,log)
    train_clean=[cleaned(w,intervals[w.company]) for w in train]
    clean_by_key={(w.company,w.as_of):w for w in train_clean}
    feature_raw=np.array([point_features(w) for w in train])
    feature_clean=np.array([point_features(w) for w in train_clean])
    cutoffs=(*VALIDATION,HOLDOUT)
    all_parts=[]
    audit=[]
    for cutoff in cutoffs:
        log(f"cutoff {cutoff}: fitting")
        fit=train_for(train,cutoff)
        fit_clean=[clean_by_key[(w.company,w.as_of)] for w in fit]
        idx=np.array([w.as_of+timedelta(days=37)<=cutoff for w in train])
        windows=control[cutoff]
        cleaned_windows=[cleaned(w,intervals[w.company]) for w in windows]
        y=np.array([w.truth[:,2] for w in windows])
        opening=np.array([w.opening for w in windows])
        p={}
        bounds={}
        reference=ProductModel(REFERENCE)
        current=ProductModel(CURRENT)
        reference_values=[]
        current_values=[]
        for w in windows:
            reference_values.append(reference.predict(w))
            current_values.append(current.predict(w))
        p["product_1_0"]=np.array([v["p50"] for v in reference_values])
        p["product_2_1"]=np.array([v["p50"] for v in current_values])
        bounds["product_2_1"]=(np.array([v["p10"] for v in current_values]),np.array([v["p90"] for v in current_values]))
        for period in (7,28,30):
            p[f"repeat_{period}"]=np.array([seasonal(w,period) for w in windows])
        p["weekday_raw"]=np.array([weekday(w) for w in windows])
        p["weekday_clean"]=np.array([weekday(w) for w in cleaned_windows])
        params={**REGRESSOR,"n_jobs":4}
        # Только вычислительный параллелизм отличается от прежних фиксированных параметров.
        import evaluation.model_compare.models as original_models
        original_models.REGRESSOR["n_jobs"]=4
        gbm=GlobalLightGBM().fit(fit)
        predictions=[gbm.predict(w) for w in windows]
        p["lgbm_raw"]=np.array([v["p50"] for v in predictions])
        bounds["lgbm_raw"]=(np.array([v["p10"] for v in predictions]),np.array([v["p90"] for v in predictions]))
        p["ensemble_50_50"]=(p["product_2_1"]+p["lgbm_raw"])/2
        bounds["ensemble_50_50"]=tuple((a+b)/2 for a,b in zip(bounds["product_2_1"],bounds["lgbm_raw"]))
        for name,learn,apply,clip in (("lgbm_unclipped",fit,windows,False),("lgbm_clean",fit_clean,cleaned_windows,True)):
            matrices=[regression_matrix(w) for w in learn]
            x=np.vstack([m[0] for m in matrices])
            target=np.concatenate([regression_targets(w,s)[0] for w,(_,s) in zip(learn,matrices)])
            model=lgb.LGBMRegressor(objective="quantile",alpha=.5,**params).fit(x,np.clip(target,-60,60) if clip else target)
            p[name]=np.array([w.opening+s*model.predict(x) for w in apply for x,s in [regression_matrix(w)]])
        for mode,learn,apply,x in (("raw",fit,windows,feature_raw[idx]),("clean",fit_clean,cleaned_windows,feature_clean[idx])):
            target=np.array([(w.truth[:,2]-w.opening)/scale(w) for w in learn])
            model=make_pipeline(SimpleImputer(strategy="median",add_indicator=True,keep_empty_features=True),StandardScaler(),Ridge(alpha=10))
            model.fit(x,target)
            predictions=model.predict(np.array([point_features(w) for w in apply]))
            p[f"ridge_{mode}"]=opening[:,None]+np.array([scale(w) for w in apply])[:,None]*predictions
            if mode=="clean":
                extra=make_pipeline(SimpleImputer(strategy="median",add_indicator=True,keep_empty_features=True),
                                    ExtraTreesRegressor(n_estimators=200,max_depth=12,min_samples_leaf=20,max_features=.8,n_jobs=4,random_state=42))
                extra.fit(x,target)
                predictions=extra.predict(np.array([point_features(w) for w in apply]))
                p["extra_trees_clean"]=opening[:,None]+np.array([scale(w) for w in apply])[:,None]*predictions
        scales=np.array([scale(w) for w in windows])
        for name,prediction in p.items():
            if prediction.shape!=y.shape or not np.isfinite(prediction).all():
                raise ValueError(f"invalid prediction {name}")
            # Хранение результатов в целых минимальных денежных единицах.
            p[name]=np.rint(prediction).astype(np.int64)
        company=np.array([hashlib.sha256(w.company.encode()).hexdigest()[:16] for w in windows])
        part={"cutoff":cutoff.isoformat(),"y":y,"opening":opening,"company":company,"scales":scales,"predictions":p,"bounds":bounds}
        all_parts.append(part)
        np.savez_compressed(PRIVATE/f"predictions-{cutoff}.npz",truth=y.astype(np.int64),opening=opening.astype(np.int64),company=company,
                            **{f"p_{k}":v for k,v in p.items()},**{f"lo_{k}":np.rint(v[0]).astype(np.int64) for k,v in bounds.items()},
                            **{f"hi_{k}":np.rint(v[1]).astype(np.int64) for k,v in bounds.items()})
        rows={name:metrics(y,pred,opening,*(bounds[name] if name in bounds else (None,None))) for name,pred in p.items()}
        save_json(OUT/f"metrics-{cutoff}.json",rows)
        clipped=np.concatenate([regression_targets(w,scale(w))[0] for w in fit])
        audit.append({"cutoff":cutoff.isoformat(),"train_windows":len(fit),"control_windows":len(windows),
                      "masked_history_windows_train":sum(not np.array_equal(a.inc,b.inc,equal_nan=True) for a,b in zip(fit,fit_clean)),
                      "masked_history_windows_control":sum(not np.array_equal(a.inc,b.inc,equal_nan=True) for a,b in zip(windows,cleaned_windows)),
                      "target_clip_fraction":float((np.abs(clipped)>60).mean())})
        log(f"cutoff {cutoff} complete; windows {len(windows)}")
    result={"protocol":"exploratory; retrospective September; no new-company holdout", "versions":{n:version(n) for n in ("numpy","scipy","scikit-learn","lightgbm","matplotlib")},
            "python":sys.version,"source_hashes":initial_hashes,"skipped":skipped,"audit":audit,
            "per_cutoff":{},"validation":{},"retrospective":{},"bootstrap":{}}
    for part in all_parts:
        result["per_cutoff"][part["cutoff"]]={k:metrics(part["y"],v,part["opening"],*(part["bounds"].get(k,(None,None)))) for k,v in part["predictions"].items()}
    for split,parts in (("validation",all_parts[:-1]),("retrospective",all_parts[-1:])):
        y=np.concatenate([r["y"] for r in parts]); op=np.concatenate([r["opening"] for r in parts])
        for name in parts[0]["predictions"]:
            pred=np.concatenate([r["predictions"][name] for r in parts])
            bound=tuple(np.concatenate([r["bounds"][name][i] for r in parts]) for i in range(2)) if name in parts[0]["bounds"] else (None,None)
            result[split][name]=metrics(y,pred,op,*bound)
        expected=1575177.46 if split=="validation" else 1072364.48
        if abs(result[split]["product_1_0"]["mae_rub"]-expected)>.02:
            raise ValueError(f"B4 reference mismatch: {split}")
    last=all_parts[-1]
    reference=np.abs(last["predictions"]["product_2_1"]-last["y"]).mean(axis=1)/100
    for name,pred in last["predictions"].items():
        delta=np.abs(pred-last["y"]).mean(axis=1)/100-reference
        result["bootstrap"][name]=bootstrap(delta,last["company"])
    candidates=[n for n in result["validation"] if not n.startswith("product_")]
    best=min(candidates,key=lambda n:result["validation"][n]["mae_rub"])
    result["selection"]={"selected_by_validation_mae":best,"retrospective_gain":1-result["retrospective"][best]["mae_rub"]/result["retrospective"]["product_2_1"]["mae_rub"],
                         "production_changed":False,"independent_confirmation":False}
    result["runtime_seconds"]=time.time()-started
    if source_hashes()!=initial_hashes: raise RuntimeError("source changed during run")
    save_json(OUT/"benchmark-results.json",result)
    log(f"complete; selected on validation: {best}; B4 verified")


if __name__=="__main__":
    with threadpool_limits(limits=4): main()
