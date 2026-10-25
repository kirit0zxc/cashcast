"""Причинное обновление LightGBM-детектора с исключением контрольных компаний."""
import argparse
from collections import Counter
from datetime import date,timedelta
import hashlib
import importlib
from importlib.metadata import version
import json
from pathlib import Path
import pickle
import sys
import types

import numpy as np

from evaluation.fallback_model.data import Dataset
from .peer_specialists import PeerPolicy
from .full_chronos import PHASES


class PeerFeatures:
    ROOT=Path('data/raw/peer-danil/export-2026-10-25/evaluation/model_compare')
    HASHES={'features.py':'f3da4bd1cf9f78de0f2b29d672ca8682136f6cfef80f6f98c50a9577cd571c93',
            'organizers.py':'37657ad4a8e17b2656ec9c644a27ee72c0128f6884ec323c84dae066215fee92'}

    @classmethod
    def load(cls):
        # Два прочитанных модуля; чужой __init__, run, notebook не запускаются.
        for name,expected in cls.HASHES.items():
            if hashlib.sha256((cls.ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:
                raise ValueError('Изменился проверенный исходник признаков')
        package=types.ModuleType('_cashcast_peer21');package.__path__=[str(cls.ROOT.resolve())]
        sys.modules.setdefault(package.__name__,package)
        features=importlib.import_module('_cashcast_peer21.features')
        organizers=importlib.import_module('_cashcast_peer21.organizers')
        return organizers.Company,features.risk_vector


class RollingPolicy:
    MODES=('static_all','rolling_all','rolling_new')
    THRESHOLDS=(.025,.05,.1,.25,.5)

    @staticmethod
    def eligible(row,cutoff,mode):
        limit=min(cutoff,date(2025,12,31)) if mode=='static_all' else cutoff
        return (not Dataset.heldout(row['company']) and date.fromisoformat(row['as_of'])+timedelta(days=37)<=limit
                and (mode!='rolling_new' or row['opening']>=0))

    @staticmethod
    def flags(rows,model,threshold):
        return [r['risk18'] or (model!='keep' and r['scores'][model]>=threshold) for r in rows]

    @classmethod
    def choose(cls,rows):
        if any(r['cutoff']>'2026-06-30' or Dataset.heldout(r['company']) for r in rows):
            raise ValueError('Поздние или контрольные компании попали в выбор')
        trials=[]
        for model,t in [('keep',.5)]+[(m,t) for m in cls.MODES for t in cls.THRESHOLDS]:
            stats=PeerPolicy.confusion(rows,cls.flags(rows,model,t));ok=True
            for month in sorted({r['cutoff'] for r in rows}):
                sub=[r for r in rows if r['cutoff']==month]
                new=PeerPolicy.confusion(sub,cls.flags(sub,model,t))
                current=PeerPolicy.confusion(sub,[r['current']>=.5 for r in sub])
                old=PeerPolicy.confusion(sub,[r['risk18'] for r in sub])
                ok &= new['tp']>=old['tp'] and new['fp']<=current['fp']
            trials.append({'model':model,'threshold':t,'eligible':bool(ok),'metrics':stats})
        choice=min([r for r in trials if r['eligible']],key=lambda r:(-r['metrics']['tp'],r['metrics']['fp'],r['model']!='keep',r['threshold'])) if sum(r['label'] for r in rows)>=5 else trials[0]
        return {'selected':choice,'trials':trials,'selection':'development January-June only'}


class RollingRisk:
    def __init__(self,output=Path('data/raw/rolling-peer-risk-v21')):
        self.output=output;output.mkdir(parents=True,exist_ok=True)

    def write(self,name,value):
        (self.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

    @staticmethod
    def dates():
        day=date(2024,10,28);result=[]
        while day+timedelta(days=37)<=date(2026,8,31):result.append(day);day+=timedelta(days=7)
        return result

    def prepare(self,source):
        data=Dataset(source);Company,features=PeerFeatures.load();train=[];control=[];excluded=Counter()
        snapshots={}
        for phase in PHASES:
            with Path(f'data/raw/chronos-finetune-v13/evaluation/inferred-{phase}.pickle').open('rb') as f:cache=pickle.load(f)
            cdf=json.loads(Path(f'data/raw/forecast-reserve-v18/{phase}-rows.json').read_text('utf-8'))
            cdf={(r['company'],r['cutoff']):r for r in cdf}
            for r in cache:
                if r['opening']<0 or r['probability'] is None:continue
                key=(r['company'],r['cutoff']);cur=r['probability']>=.5
                chrono=cur if r['fallback'] else bool(np.any(r['intervals']['ft100'][:,0]<0))
                snapshots[key]={'company':r['company'],'cutoff':r['cutoff'],'phase':phase,
                                'label':bool(np.any(r['truth'][:,2]<0)),'current':r['probability'],
                                'risk18':cur and (chrono or cdf[key]['scores']['forecast6']['30']>=.3)}
        feature_checks=[]
        for index,company in enumerate(sorted(data.transactions)):
            txns=data.transactions[company];balances=data.balances[company]
            ctx=Company(company,txns,balances)
            if not Dataset.heldout(company):
                for day in self.dates():
                    w,reason=ctx.window(txns,balances,day,False)
                    if w is None:excluded[reason]+=1;continue
                    train.append({'company':company,'as_of':str(day),'opening':w.opening,
                                  'features':features(w),'label':bool(w.label)})
            for (owner,day),r in snapshots.items():
                if owner!=company:continue
                cutoff=date.fromisoformat(day);w=ctx.snapshot(cutoff);x=features(w)
                control.append({**r,'features':x})
                if len(feature_checks)<3:
                    causal=Company(company,[t for t in txns if t.booked_on<=cutoff],{d:b for d,b in balances.items() if d<=cutoff})
                    np.testing.assert_allclose(x,features(causal.snapshot(cutoff)),rtol=0,atol=0,equal_nan=True)
                    feature_checks.append([company,day])
            if (index+1)%10==0:print(f'Prepared {index+1}/150 companies, train={len(train)}',flush=True)
        self.write('sources.json',{'dataset_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                                  'peer_features_sha256':PeerFeatures.HASHES,'excluded':dict(excluded),
                                  'future_feature_checks':feature_checks,'train_windows':len(train),'control_windows':len(control)})
        # Эти pickle созданы здесь; не принимаются от внешних отправителей.
        with (self.output/'prepared.pickle').open('wb') as f:pickle.dump({'train':train,'control':control},f)
        print('Preparation complete',flush=True)

    def run(self):
        import lightgbm as lgb
        self.write('environment.json',{'python':sys.version,'packages':{n:version(n) for n in ('lightgbm','scikit-learn','numpy','scipy')},
                                     'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        with (self.output/'prepared.pickle').open('rb') as f:prepared=pickle.load(f)
        train,control=prepared['train'],prepared['control'];audits={};static=None
        for cutoff in sorted({r['cutoff'] for r in control}):
            now=date.fromisoformat(cutoff);test=[r for r in control if r['cutoff']==cutoff]
            x_test=np.array([r['features'] for r in test])
            for mode in RollingPolicy.MODES:
                selected=[r for r in train if RollingPolicy.eligible(r,now,mode)]
                labels=np.array([r['label'] for r in selected]);x=np.array([r['features'] for r in selected])
                if len(set(labels))<2:raise ValueError('Недостаточно классов')
                model=static if mode=='static_all' else None
                if model is None:
                    model=lgb.LGBMClassifier(n_estimators=300,learning_rate=.03,num_leaves=15,min_child_samples=50,
                        reg_lambda=5.,random_state=42,deterministic=True,force_row_wise=True,verbose=-1,
                        subsample=.8,subsample_freq=1,colsample_bytree=.8,n_jobs=4)
                    model.fit(x,labels)
                    if mode=='static_all':static=model
                scores=model.predict_proba(x_test)[:,1]
                name=f'{cutoff}-{mode}.txt';model.booster_.save_model(str(self.output/name))
                loaded=lgb.Booster(model_file=str(self.output/name));again=loaded.predict(x_test,num_threads=4)
                np.testing.assert_allclose(scores,again,atol=1e-12,rtol=0)
                for r,p in zip(test,scores,strict=True):r.setdefault('scores',{})[mode]=float(p)
                max_confirmation=max(date.fromisoformat(r['as_of'])+timedelta(days=37) for r in selected)
                assert max_confirmation<=now and all(not Dataset.heldout(r['company']) for r in selected)
                audits[f'{cutoff}/{mode}']={'windows':len(selected),'positives':int(labels.sum()),
                    'positive_companies':len({r['company'] for r in selected if r['label']}),
                    'max_confirmation':str(max_confirmation),'weights_sha256':hashlib.sha256((self.output/name).read_bytes()).hexdigest(),
                    'window_identity_sha256':hashlib.sha256(repr([(r['company'],r['as_of']) for r in selected]).encode()).hexdigest(),
                    'reload_max_abs_diff':float(np.max(abs(scores-again)))}
            self.write('training-audit.json',audits)
            print(f'Trained/evaluated {cutoff}',flush=True)
        early=[r for r in control if r['phase'] in ('validation','bridge')]
        selection=RollingPolicy.choose(early);self.write('selection-frozen.json',selection)
        choice=selection['selected'];report={'selection':selection,'phases':{},'production_activated':False,'independent_control':False,
            'heldout_companies_excluded_from_training':True,'probability_calibrated':False}
        for phase in PHASES:
            rows=[r for r in control if r['phase']==phase];y=np.array([r['label'] for r in rows],float)
            proper={}
            for mode in RollingPolicy.MODES:
                p=np.array([r['scores'][mode] for r in rows]);q=np.clip(p,1e-8,1-1e-8)
                proper[mode]={'brier':float(np.mean((p-y)**2)),
                              'logloss':float(-np.mean(y*np.log(q)+(1-y)*np.log(1-q)))}
            report['phases'][phase]={'windows':len(rows),'positive_companies':len({r['company'] for r in rows if r['label']}),
                'current':PeerPolicy.confusion(rows,[r['current']>=.5 for r in rows]),
                'candidate18':PeerPolicy.confusion(rows,[r['risk18'] for r in rows]),
                'candidate21':PeerPolicy.confusion(rows,RollingPolicy.flags(rows,choice['model'],choice['threshold'])),
                'proper_scores':proper}
            self.write(f'{phase}-rows.json',[{k:v for k,v in r.items() if k!='features'} for r in rows])
        self.write('results.json',report)
        print(json.dumps(selection['selected'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','train'));parser.add_argument('--zip',type=Path)
    args=parser.parse_args();study=RollingRisk()
    if args.stage=='prepare':
        if args.zip is None:parser.error('--zip обязателен')
        study.prepare(args.zip)
    else:study.run()
