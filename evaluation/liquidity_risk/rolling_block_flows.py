"""Причинное обновление моделей сумм блоков с исключением группы компании."""
import argparse
from collections import Counter
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from evaluation.backtest import fold
from evaluation.fallback_model.data import Dataset
from .block_flows import BlockMath,BlockStudy
from .company_crossfit import CrossfitPolicy
from .distribution_run import DistributionExperiment
from .full_chronos import PHASES
from .horizon_ensemble import HorizonWeights
from .research_audit import cash_metrics,cluster_intervals,deltas,digest,write_json


class RollingBlockMath:
    @staticmethod
    def eligible(row,cutoff,excluded):
        return (not Dataset.heldout(row['company']) and CrossfitPolicy.group(row['company'])!=excluded
                and date.fromisoformat(row['as_of'])+timedelta(days=37)<=cutoff)

    @staticmethod
    def training(rows):
        counts=Counter(r['company'] for r in rows);x=[];y=[];weights=[]
        for row in rows:
            scale=row['scale']
            if not np.isfinite(scale) or scale<=0:raise ValueError('Некорректный прошлый масштаб')
            truth=np.asarray(row['truth'])
            if truth.shape!=(30,3) or np.any(truth[:,:2]<0):raise ValueError('Неверная цель потоков')
            x.extend(BlockMath.features(row))
            for start,end in BlockMath.BLOCKS:
                y.append(truth[start:end,:2].sum(axis=0)/(scale*(end-start)))
                weights.append(scale*(end-start)/counts[row['company']])
        w=np.asarray(weights);w/=w.mean()
        return np.asarray(x),np.asarray(y),w


class RollingBlockStudy(BlockStudy):
    def __init__(self,source,output):
        super().__init__(source,output);self.group_models={};self.audits={}
        self.sources.update(code=digest(Path(__file__)),protocol=digest(Path('journal/36_rolling_block_flows.md')),
                            base_block_code=digest(Path('evaluation/liquidity_risk/block_flows.py')))

    def train(self):
        path=Path('data/raw/long-history-risk-v31/prepared.pickle')
        started=json.loads(path.with_name('started.json').read_text('utf-8'))
        if digest(path)!=started['prepared86_sha256']:raise ValueError('Изменился список исходных окон31')
        with path.open('rb') as stream:original=pickle.load(stream)['train']
        self.sources['training_identities_source']=digest(path)
        write_json(self.output/'preparation-started.json',{'params':self.PARAMS,'sources_sha256':self.sources})
        self.training_rows=[];excluded=0
        for index,row in enumerate(original):
            cutoff=date.fromisoformat(row['as_of'])
            entry,reason=fold(row['company'],self.data.transactions[row['company']],self.data.balances[row['company']],cutoff)
            if entry is None:raise ValueError('Не восстановлено окно21: '+str(reason))
            snapshot,truth,_=entry
            if snapshot.opening_balance_minor!=row['opening'] or bool(np.any(np.asarray(truth)[:,2]<0))!=row['label']:
                raise ValueError('Изменился исходный остаток/метка')
            prepared=DistributionExperiment.make(snapshot,np.asarray(truth))
            if prepared['history_days']<28:excluded+=1;continue
            prepared['base_features']=prepared.pop('features');prepared['as_of']=row['as_of']
            prepared['opening']=snapshot.opening_balance_minor
            self.training_rows.append(prepared)
            if (index+1)%2000==0:print(f'Rolling36 prepared {index+1}/{len(original)}',flush=True)
        with (self.output/'prepared-train.pickle').open('wb') as stream:pickle.dump(self.training_rows,stream)
        self.sources['prepared_train_sha256']=digest(self.output/'prepared-train.pickle')
        write_json(self.output/'started.json',{'params':self.PARAMS,'sources_sha256':self.sources,
            'source_windows':len(original),'training_windows':len(self.training_rows),'excluded_history_below28':excluded,
            'companies':len({r['company'] for r in self.training_rows}),'negative_opening_allowed_for_flows':True})

    def train_cutoff(self,cutoff):
        from catboost import CatBoostRegressor
        if cutoff in self.group_models:return
        self.group_models[cutoff]={}
        for excluded in range(5):
            rows=[r for r in self.training_rows if RollingBlockMath.eligible(r,date.fromisoformat(cutoff),excluded)]
            x,y,w=RollingBlockMath.training(rows);self.group_models[cutoff][excluded]=[]
            for channel in range(2):
                model=CatBoostRegressor(**self.PARAMS);model.fit(x,y[:,channel],sample_weight=w)
                target=self.output/f'{cutoff}-exclude{excluded}-channel{channel}.cbm';model.save_model(str(target))
                loaded=CatBoostRegressor();loaded.load_model(str(target))
                np.testing.assert_allclose(model.predict(x[:30]),loaded.predict(x[:30]),atol=1e-12,rtol=0)
                self.group_models[cutoff][excluded].append(loaded)
                self.audits[f'{cutoff}/{excluded}/{channel}']={'windows':len(rows),'companies':len({r['company'] for r in rows}),
                    'excluded_group':excluded,'heldout_excluded':True,
                    'max_confirmation':str(max(date.fromisoformat(r['as_of'])+timedelta(days=37) for r in rows)),
                    'identities_sha256':hashlib.sha256(repr([(r['company'],r['as_of']) for r in rows]).encode()).hexdigest(),
                    'sample_weights_sha256':hashlib.sha256(w.tobytes()).hexdigest(),'weights_sha256':digest(target)}
                write_json(self.output/'training-audit.json',self.audits)
            print(f'Rolling36 trained {cutoff} excluded={excluded}',flush=True)

    def infer(self,phase):
        path=Path('data/raw/chronos-specialists-v8')/f'inferred-{phase}.pickle'
        with path.open('rb') as stream:rows=pickle.load(stream)['rows']
        self.sources['cache_'+phase]=digest(path)
        windows,_=self.data.windows(*PHASES[phase]);lookup={(s.account_id,str(s.as_of)):(s,t) for s,t,_ in windows}
        if len(lookup)!=len(rows):raise ValueError('Изменился состав оценки')
        for row in rows:
            snapshot,truth=lookup[(row['company'],row['cutoff'])]
            np.testing.assert_array_equal(truth,row['truth'])
            values=np.stack([row['models'][m][:,2] for m in ('current','direct','balance365')],axis=1)[None]
            row['models']['candidate18']=row['models']['current'].copy()
            row['models']['candidate18'][:,2]=HorizonWeights.predict(values,0.,(.5,1.,.75))[0]
            row['models']['benchmark75_25']=row['models']['blend75'].copy()
            if row['fallback']:
                for a in BlockMath.ALPHAS:row['models'][f'block{a}']=row['models']['current'].copy()
                continue
            prepared=DistributionExperiment.make(snapshot,truth);prepared['base_features']=prepared.pop('features')
            x=BlockMath.features(prepared);self.train_cutoff(row['cutoff'])
            groups=list(range(5)) if Dataset.heldout(row['company']) else [CrossfitPolicy.group(row['company'])]
            predictions=np.mean([np.stack([model.predict(x,thread_count=4) for model in self.group_models[row['cutoff']][g]],axis=1) for g in groups],axis=0)
            for a in BlockMath.ALPHAS:row['models'][f'block{a}']=BlockMath.predict(row,predictions,prepared['scale'],a)
        print(f'Rolling36 inferred {phase} {len(rows)}',flush=True)
        return rows

    def run(self):
        self.train();early=self.infer('validation');selection=BlockMath.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        write_json(self.output/'selection-lock.json',{'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Frozen36: '+str(selection['selected']),flush=True)
        phases={'validation':early}
        for phase in PHASES:
            if phase!='validation':phases[phase]=self.infer(phase)
        models=('current','benchmark75_25','candidate18','candidate30',*(f'block{a}' for a in BlockMath.ALPHAS),'selected36')
        report={'selection':selection,'training_mode':'rolling_company_crossfit','independent_control':False,'production_activated':False,
                'risk_unchanged':'18/21/25/29/31','phases':{},'sources_sha256':self.sources}
        details={}
        for phase,rows in phases.items():
            oldpath=Path('data/raw/block-flows-v30')/f'inferred-{phase}.pickle'
            with oldpath.open('rb') as stream:old=pickle.load(stream)
            if [(r['company'],r['cutoff']) for r in rows]!=[(r['company'],r['cutoff']) for r in old]:raise ValueError('Изменились окна30')
            for row,original in zip(rows,old,strict=True):
                np.testing.assert_array_equal(row['truth'],original['truth'])
                np.testing.assert_array_equal(row['models']['current'],original['models']['current'])
                row['models']['candidate30']=original['models']['selected30'].copy()
                row['models']['selected36']=row['models'][selection['selected']['model']].copy()
            self.sources['reference30_'+phase]=digest(oldpath)
            with (self.output/f'inferred-{phase}.pickle').open('wb') as stream:pickle.dump(rows,stream)
            report['phases'][phase]={'scores':{m:{str(h):cash_metrics(rows,m,h) for h in (7,14,30)} for m in models},
                'deltas':{base:{str(h):deltas(cash_metrics(rows,'selected36',h),cash_metrics(rows,base,h)) for h in (7,14,30)}
                          for base in ('current','benchmark75_25','candidate18','candidate30')},
                'cluster_intervals':{str(h):cluster_intervals(rows,'selected36','current',h) for h in (7,14,30)}}
            details[phase]={mode:{key:{m:{str(h):cash_metrics([r for r in rows if r[mode]==key],m,h) for h in (7,14,30)}
                for m in models} for key in sorted({r[mode] for r in rows})} for mode in ('company','cutoff')}
        keys=tuple(set(BlockMath.OBJECTIVE+BlockMath.GUARDS))
        report['preliminary_transfer']=bool(selection['selected']['alpha'] is not None and all(
            p['scores']['selected36'][str(h)][k]<=p['scores']['current'][str(h)][k]*1.05
            for phase,p in report['phases'].items() if phase!='validation' for h in (7,14,30) for k in keys))
        write_json(self.output/'results.json',report);write_json(self.output/'by-company-and-period.json',details)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json')})
        print('Rolling36 complete; preliminary_transfer='+str(report['preliminary_transfer']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/raw/rolling-block-flows-v36'))
    args=parser.parse_args();RollingBlockStudy(args.zip,args.output).run()
