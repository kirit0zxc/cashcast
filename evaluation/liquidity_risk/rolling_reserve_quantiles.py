"""Причинные квантили денежного резерва на86признаках31."""
import argparse
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from evaluation.backtest import fold
from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from .company_crossfit import CrossfitExperiment,CrossfitPolicy
from .research_audit import digest,write_json


class ReservePolicy:
    QUANTILES=(.9,.95,.99)

    @staticmethod
    def target(truth,opening):
        truth=np.asarray(truth)
        if truth.shape!=(30,3) or not np.isfinite(truth).all():raise ValueError('Неверная форма целей')
        np.testing.assert_array_equal(opening+np.cumsum(truth[:,0]-truth[:,1]),truth[:,2])
        reserve=max(0.,-float(np.cumsum(truth[:,0]-truth[:,1]).min()))
        if opening>=0 and bool(opening<reserve)!=bool(np.any(truth[:,2]<0)):
            raise ValueError('Нарушена идентичность резерва и нового разрыва')
        return reserve

    @classmethod
    def flags(cls,rows,choice):
        if choice['mode']=='keep31':return [r['risk31'] for r in rows]
        key=str(choice['quantile'])
        flags=[r['opening']<r['reserve_quantiles_minor'][key] for r in rows]
        if choice['mode']=='alone':return flags
        if choice['mode']=='or18':return [r['risk18'] or value for r,value in zip(rows,flags,strict=True)]
        raise ValueError('Неизвестная политика34')

    @classmethod
    def choose(cls,rows):
        if not rows or any(Dataset.heldout(r['company']) or r['phase'] not in CrossfitPolicy.EARLY or r['cutoff']>'2026-06-30' for r in rows):
            raise ValueError('Выбор толькораннийdevelopment')
        choices=[{'mode':'keep31','quantile':None}]+[{'mode':m,'quantile':q} for m in ('or18','alone') for q in cls.QUANTILES]
        trials=[];enough=sum(r['label'] for r in rows)>=5
        for choice in choices:
            eligible=choice['mode']=='keep31' or enough
            for cutoff in sorted({r['cutoff'] for r in rows}):
                group=[r for r in rows if r['cutoff']==cutoff];labels=[r['label'] for r in group]
                new=Score.classification(labels,cls.flags(group,choice))
                old=Score.classification(labels,[r['risk31'] for r in group])
                current=Score.classification(labels,[r['current']>=.5 for r in group])
                if choice['mode']!='keep31':eligible &= new['tp']>=old['tp'] and new['fp']<=current['fp']
            trials.append({**choice,'eligible':bool(eligible),'metrics':Score.classification([r['label'] for r in rows],cls.flags(rows,choice))})
        order={'keep31':0,'or18':1,'alone':2}
        selected=min((t for t in trials if t['eligible']),key=lambda t:(-t['metrics']['tp'],t['metrics']['fp'],order[t['mode']],t['quantile'] or 0))
        return {'selected':selected,'trials':trials,'selection':'development January-June only'}


class ReserveStudy:
    PARAMS={k:v for k,v in CrossfitExperiment.PARAMS.items()}

    def __init__(self,dataset,output):
        if output.exists():raise FileExistsError('Каталог существует; проверить процесс')
        source=Path('data/raw/long-history-risk-v31')
        started=json.loads((source/'started.json').read_text('utf-8'))
        if digest(source/'prepared.pickle')!=started['prepared86_sha256']:raise ValueError('Изменились признаки31')
        with (source/'prepared.pickle').open('rb') as stream:prepared=pickle.load(stream)
        output.mkdir(parents=True);self.output=output;self.train=prepared['train'];self.control=prepared['control'];self.models={};self.audits={}
        reference31={(r['company'],r['cutoff']):r for r in json.loads((source/'predictions.json').read_text('utf-8'))}
        path29=Path('data/raw/diverse-risk-v29/predictions.json')
        reference29={(r['company'],r['cutoff']):r for r in json.loads(path29.read_text('utf-8'))}
        for row in self.control:
            a=reference31[(row['company'],row['cutoff'])];b=reference29[(row['company'],row['cutoff'])]
            if any(row[k]!=ref[k] for ref in (a,b) for k in ('label','current','risk18','risk21','phase')):raise ValueError('Разошлись baseline')
            row['risk31']=bool(row['risk18'] or a['extended_score']>=.1)
            row['risk29']=bool(row['risk18'] or .5*(b['cat_score']+b['score25'])>=.05)
        self.sources={'dataset_sha256':digest(dataset),'prepared31_sha256':digest(source/'prepared.pickle'),
            'predictions31_sha256':digest(source/'predictions.json'),'predictions29_sha256':digest(path29),
            'protocol_sha256':digest(Path('journal/34_rolling_reserve_quantiles.md')),'code_sha256':digest(Path(__file__))}
        data=Dataset(dataset)
        for label,rows in (('train',self.train),('control',self.control)):
            for index,row in enumerate(rows):
                cutoff=date.fromisoformat(row.get('as_of',row.get('cutoff')))
                entry,reason=fold(row['company'],data.transactions[row['company']],data.balances[row['company']],cutoff)
                if entry is None:raise ValueError('Исходное окно не восстановлено: '+str(reason))
                snapshot,truth,_=entry
                if label=='train' and snapshot.opening_balance_minor!=row['opening']:raise ValueError('Изменился обучающий остаток')
                if bool(np.any(np.asarray(truth)[:,2]<0))!=row['label']:raise ValueError('Изменилась исходная метка')
                row['opening']=snapshot.opening_balance_minor
                row['reserve_minor']=ReservePolicy.target(truth,row['opening'])
                row['reserve_scale']=float(10.**row['features'][1])
                if not np.isfinite(row['reserve_scale']) or row['reserve_scale']<9999.999:
                    raise ValueError('Некорректный прошлый масштаб')
                if len(row['features'])!=86:raise ValueError('Изменилась схема31')
                if (index+1)%2000==0:print(f'Reserve34 targets verified {label} {index+1}',flush=True)
        with (output/'prepared.pickle').open('wb') as stream:pickle.dump({'train':self.train,'control':self.control},stream)
        write_json(output/'started.json',{'params':self.PARAMS,'quantiles':ReservePolicy.QUANTILES,**self.sources,
            'train_windows':len(self.train),'control_windows':len(self.control),'target_identity_verified':True,
            'prepared_sha256':digest(output/'prepared.pickle')})

    def train_cutoff(self,cutoff):
        import lightgbm as lgb
        if cutoff in self.models:return
        self.models[cutoff]={}
        for excluded in range(5):
            rows=[r for r in self.train if CrossfitPolicy.eligible(r,date.fromisoformat(cutoff),excluded)]
            x=np.asarray([r['features'] for r in rows]);y=np.asarray([r['reserve_minor']/r['reserve_scale'] for r in rows])
            w=CrossfitPolicy.weights(rows);self.models[cutoff][excluded]={}
            for q in ReservePolicy.QUANTILES:
                model=lgb.LGBMRegressor(**self.PARAMS,objective='quantile',alpha=q)
                model.fit(x,y,sample_weight=w)
                target=self.output/f'{cutoff}-exclude{excluded}-q{q}.txt';model.booster_.save_model(str(target))
                loaded=lgb.Booster(model_file=str(target))
                np.testing.assert_allclose(model.booster_.predict(x[:20],num_threads=4),loaded.predict(x[:20],num_threads=4),atol=1e-12,rtol=0)
                self.models[cutoff][excluded][q]=loaded
                self.audits[f'{cutoff}/{excluded}/{q}']={'windows':len(rows),'companies':len({r['company'] for r in rows}),
                    'positive_windows':sum(r['label'] for r in rows),'excluded_group':excluded,'heldout_excluded':True,
                    'max_confirmation':str(max(date.fromisoformat(r['as_of'])+timedelta(days=37) for r in rows)),
                    'identities_sha256':hashlib.sha256(repr([(r['company'],r['as_of']) for r in rows]).encode()).hexdigest(),
                    'sample_weights_sha256':hashlib.sha256(w.tobytes()).hexdigest(),'weights_sha256':digest(target)}
                write_json(self.output/'training-audit.json',self.audits)
            print(f'Reserve34 trained {cutoff} excluded={excluded}',flush=True)

    def predict(self,rows):
        for cutoff in sorted({r['cutoff'] for r in rows}):
            self.train_cutoff(cutoff);group=[r for r in rows if r['cutoff']==cutoff]
            x=np.asarray([r['features'] for r in group])
            values=np.stack([np.stack([self.models[cutoff][g][q].predict(x,num_threads=4) for q in ReservePolicy.QUANTILES],axis=1) for g in range(5)],axis=1)
            for row,value in zip(group,values,strict=True):
                raw=value.mean(axis=0) if Dataset.heldout(row['company']) else value[CrossfitPolicy.group(row['company'])]
                projected=np.sort(np.maximum(raw,0))*row['reserve_scale']
                if not np.isfinite(projected).all() or np.max(projected)>9e15:raise ValueError('Неверный резерв')
                row['reserve_quantiles_minor']={str(q):float(v) for q,v in zip(ReservePolicy.QUANTILES,projected,strict=True)}

    @staticmethod
    def metrics(rows,choice):
        labels=[r['label'] for r in rows]
        flags={f'candidate{n}':[r[f'risk{n}'] for r in rows] for n in (18,21,25,29,31)}
        flags['current']=[r['current']>=.5 for r in rows];flags['selected34']=ReservePolicy.flags(rows,choice)
        return {name:Score.classification(labels,f) for name,f in flags.items()}

    @staticmethod
    def quantile_metrics(rows):
        result={}
        for q in ReservePolicy.QUANTILES:
            errors=np.asarray([r['reserve_minor']-r['reserve_quantiles_minor'][str(q)] for r in rows])
            losses=np.maximum(q*errors,(q-1)*errors)
            result[str(q)]={'n':len(rows),'pinball_rub':float(losses.mean()/100),
                'pinball_normalized':float(np.mean(losses/np.asarray([r['reserve_scale'] for r in rows]))),
                'coverage':float(np.mean(errors<=0)),'nominal_coverage':q,'calibrated':False}
        return result

    def run(self):
        early=[r for r in self.control if r['phase'] in CrossfitPolicy.EARLY]
        self.predict(early);selection=ReservePolicy.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        write_json(self.output/'selection-lock.json',{'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Frozen34: '+str(selection['selected']),flush=True)
        self.predict([r for r in self.control if r['phase'] not in CrossfitPolicy.EARLY]);choice=selection['selected']
        report={'selection':selection,'independent_control':False,'production_activated':False,'probability_any_negative':None,
                'brier':None,'brier_reason':'monetary_quantiles_are_not_probabilities','total':self.metrics(self.control,choice),'phases':{}}
        for phase in sorted({r['phase'] for r in self.control}):
            rows=[r for r in self.control if r['phase']==phase]
            report['phases'][phase]={'metrics':self.metrics(rows,choice),'quantile_diagnostics':self.quantile_metrics(rows),
                'all_fixed_policies':{mode:{str(q):Score.classification([r['label'] for r in rows],ReservePolicy.flags(rows,{'mode':mode,'quantile':q}))
                    for q in ReservePolicy.QUANTILES} for mode in ('or18','alone')}}
        old,new=report['total']['candidate31'],report['total']['selected34']
        preserved=all(p['metrics']['selected34']['tp']>=p['metrics']['candidate31']['tp'] for p in report['phases'].values())
        report['preliminary_dominance']=bool(preserved and new['tp']>=old['tp'] and new['fp']<old['fp'])
        report['preliminary_recall_tradeoff']=bool(preserved and new['tp']>old['tp'] and new['fp']<=report['total']['candidate25']['fp'])
        flags=ReservePolicy.flags(self.control,choice)
        transformed=[{**r,'risk21':r['risk31'],'risk18':False,'crossfit_score':float(f)} for r,f in zip(self.control,flags,strict=True)]
        report['paired_company_bootstrap']=CrossfitExperiment.cluster_bootstrap(transformed,.5)
        report['paired_company_bootstrap']['comparison']='selected34_minus_candidate31'
        for mode in ('cutoff','company'):
            report['by_'+mode]={key:self.metrics([r for r in self.control if r[mode]==key],choice) for key in sorted({r[mode] for r in self.control})}
        write_json(self.output/'predictions.json',[{k:v for k,v in r.items() if k!='features'} for r in self.control])
        write_json(self.output/'results.json',report)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json'),'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Reserve34 complete: '+str(report['total']['selected34']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/raw/rolling-reserve-quantiles-v34'))
    args=parser.parse_args();ReserveStudy(args.zip,args.output).run()
