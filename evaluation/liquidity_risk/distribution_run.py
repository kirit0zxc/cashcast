"""Обучение на прошлом и парное сравнение с сохранённым опытом08."""
import argparse
import hashlib
import json
import pickle
import sys
import time
from datetime import date,timedelta
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"backend"))
from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from evaluation.real_data.risk import metrics
from .distribution import DistributionModel,DistributionQueries,HORIZONS
from .full_chronos import PHASES
from .model import ReserveFeatures


class DistributionExperiment:
    def __init__(self,source,reference,output):
        self.data=Dataset(source);self.reference=reference;self.output=output
        output.mkdir(parents=True,exist_ok=True)
        self.models={}
        self.report={"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
                     "production_activated":False,"calibrated":False,"independent_control":False}

    def write(self,name,value):
        (self.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

    @staticmethod
    def make(snapshot,truth):
        features,scale,quality,_=ReserveFeatures.make(snapshot)
        return {"company":snapshot.account_id,"cutoff":snapshot.as_of.isoformat(),"features":features,
                "scale":scale,"opening":snapshot.opening_balance_minor/scale,"truth":truth,
                "history_days":quality.history_days}

    def train(self):
        dates=[];day=date(2024,12,31)
        while day+timedelta(days=30)<=date(2025,12,31):
            dates.append(day);day+=timedelta(days=14)
        windows,excluded=self.data.windows(dates,date(2025,12,31))
        rows=[self.make(s,t) for s,t,_ in windows]
        rows=[r for r in rows if r["history_days"]>=28]
        fit=[r for r in rows if r["opening"]>=0]
        self.priors={str(h):(sum(np.any(r["truth"][:h,2]<0) for r in fit)+.5)/(len(fit)+1) for h in HORIZONS}
        x,y,w=DistributionQueries.augment(rows)
        self.report["train"]={"windows":len(rows),"companies":len({r['company'] for r in rows}),
                              "expanded_queries":len(y),"query_positive_fraction":float(y.mean()),
                              "natural_positive_windows":{str(h):sum(bool(np.any(r['truth'][:h,2]<0)) for r in fit) for h in HORIZONS},
                              "natural_priors":self.priors,"excluded":excluded,"target_end":"2025-12-31"}
        self.write("results.json",self.report)
        for depth in (4,6):
            started=time.perf_counter()
            name=f"cdf{depth}";model=DistributionModel(depth).fit(x,y,w)
            model.model.save_model(str(self.output/f"{name}.cbm"));self.models[name]=model
            print(f"Trained {name}: {len(y)} queries, {time.perf_counter()-started:.1f}s",flush=True)

    def prepare(self,phase):
        windows,excluded=self.data.windows(*PHASES[phase])
        with (self.reference/f"inferred-{phase}.pickle").open("rb") as stream:
            previous=pickle.load(stream)["rows"]
        lookup={(r['company'],r['cutoff']):r for r in previous}
        rows=[]
        for snapshot,truth,_ in windows:
            row=self.make(snapshot,truth)
            original=lookup[(row['company'],row['cutoff'])]
            np.testing.assert_array_equal(truth,original['truth'])
            row['current']=original['probability']
            row['scores']={}
            if row['opening']<0 or row['current'] is None: continue
            rows.append(row)
        for horizon in HORIZONS:
            queries=[DistributionQueries.query(r['features'],horizon,r['opening']) for r in rows]
            for name,model in self.models.items():
                predictions=model.predict(queries)
                for row,p in zip(rows,predictions,strict=True): row['scores'].setdefault(name,{})[str(horizon)]=float(p)
        return rows,excluded

    def statistics(self,rows,name,horizon=30,threshold=.5):
        y=[bool(np.any(r['truth'][:horizon,2]<0)) for r in rows]
        p=[r['current'] if name=='current' else r['scores'][name][str(horizon)] for r in rows]
        report={**metrics(y,p,threshold,self.priors[str(horizon)]),**Score.classification(y,np.asarray(p)>=threshold)}
        clipped=np.clip(p,1e-12,1-1e-12);labels=np.asarray(y,dtype=float)
        report['log_loss']=float(np.mean(-labels*np.log(clipped)-(1-labels)*np.log(1-clipped)))
        report['positive_companies']=len({r['company'] for r,label in zip(rows,y) if label})
        return report

    @staticmethod
    def policy_stats(rows,name,threshold,mode):
        y=[bool(np.any(r['truth'][:,2]<0)) for r in rows]
        current=np.array([r['current']>=.5 for r in rows])
        candidate=np.array([r['scores'][name]['30']>=threshold for r in rows]) if name!='current' else current
        flags={'candidate':candidate,'intersection':current&candidate,'union':current|candidate}[mode]
        report=Score.classification(y,flags)
        report['fpr']=report['fp']/(report['fp']+report['tn']) if report['fp']+report['tn'] else None
        return report

    def choose_policy(self,rows,name):
        baseline=self.policy_stats(rows,'current',.5,'candidate')
        choices=[{'model':'current','threshold':.5,'mode':'candidate','statistics':baseline}]
        for threshold in (.01,.02,.05,.1,.15,.2,.3,.4,.5,.6,.7,.8,.9):
            for mode in ('candidate','intersection','union'):
                stats=self.policy_stats(rows,name,threshold,mode)
                choices.append({'model':name,'threshold':threshold,'mode':mode,'statistics':stats})
        allowed=[c for c in choices if baseline['positives']>=5 and c['statistics']['recall']>=baseline['recall'] and c['statistics']['fpr']<=baseline['fpr']]
        selected=min(allowed,key=lambda c:(c['statistics']['fp'],c['statistics']['fn'],c['model']!='current',c['threshold'])) if allowed else choices[0]
        return {'selected':selected,'trials':choices,'selection':'natural development January-June only'}

    def run(self,resume=False):
        if resume:
            from catboost import CatBoostClassifier
            saved=json.loads((self.output/'results.json').read_text(encoding='utf-8'))
            if saved['source_sha256']!=self.report['source_sha256']: raise ValueError('Другой исходный набор')
            self.report=saved;self.priors=saved['train']['natural_priors']
            for depth in (4,6):
                model=DistributionModel(depth);model.model=CatBoostClassifier()
                model.model.load_model(str(self.output/f'cdf{depth}.cbm'))
                params=model.model.get_all_params()
                if params['depth']!=depth or params['iterations']!=600 or params['random_seed']!=20261025:
                    raise ValueError('Веса не соответствуют протоколу09')
                self.models[f'cdf{depth}']=model
        else:
            self.train()
        validation,_=self.prepare('validation')
        natural={name:{str(h):self.statistics(validation,name,h) for h in HORIZONS} for name in self.models}
        selected=min(self.models,key=lambda n:np.mean([natural[n][str(h)]['log_loss'] for h in HORIZONS]))
        self.report['model_selection']={'selected':selected,'natural_validation':natural,'selection':'January-March logloss only'}
        self.write('model-selection-frozen.json',self.report['model_selection'])
        bridge,_=self.prepare('bridge')
        policy=self.choose_policy(validation+bridge,selected)
        self.report['policy_selection']=policy
        self.write('policy-selection-frozen.json',policy)
        self.report['phases']={}
        for phase in PHASES:
            rows=validation if phase=='validation' else bridge if phase=='bridge' else self.prepare(phase)[0]
            p=policy['selected']
            self.report['phases'][phase]={
                'candidate':{str(h):self.statistics(rows,selected,h) for h in HORIZONS},
                'current_30':self.statistics(rows,'current'),
                'selected_policy':self.policy_stats(rows,p['model'],p['threshold'],p['mode'])}
            serial=[{k:r[k] for k in ('company','cutoff','opening','current','scores')} |
                    {'labels':{str(h):bool(np.any(r['truth'][:h,2]<0)) for h in HORIZONS}} for r in rows]
            self.write(f'{phase}-rows.json',serial)
            self.write('results.json',self.report)
            print(f'Evaluated {phase}: {len(rows)} windows; model={selected}',flush=True)
        self.report['weights_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.glob('*.cbm')}
        self.report['release_allowed']=False
        self.write('results.json',self.report)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    DistributionExperiment(args.zip,args.reference,args.output).run(args.resume)


if __name__=='__main__': main()
