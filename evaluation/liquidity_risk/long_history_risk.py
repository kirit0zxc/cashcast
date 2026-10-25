"""Длинная история денежных провалов поверх причинных признаков25."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import pickle

import numpy as np

from evaluation.fallback_model.data import Dataset
from app.modules.contracts import Direction
from evaluation.fallback_model.metrics import Score
from .company_crossfit import CrossfitExperiment, CrossfitPolicy
from .diverse_risk import DiverseExperiment, DiversePolicy
from .research_audit import digest, reliability, write_json


class LongHistoryFeatures:
    WINDOWS = (28,84,180,365)

    @classmethod
    def make(cls, company, cutoff, transactions):
        past = [t for t in transactions if t.account_id==company and t.booked_on<=cutoff]
        if not past: raise ValueError('Нет прошлого компании')
        start = max(min(t.booked_on for t in past), cutoff-timedelta(days=364))
        daily = np.zeros(((cutoff-start).days+1,2),dtype=float)
        for txn in past:
            if txn.booked_on>=start:
                daily[(txn.booked_on-start).days,0 if txn.direction==Direction.IN else 1] += txn.amount_minor
        scale = max(10000.,*daily[-84:].mean(axis=0))
        output = []
        for window in cls.WINDOWS:
            values=daily[-window:]/scale;net=values[:,0]-values[:,1]
            path=np.r_[0.,np.cumsum(net)]
            drawdown=float(np.max(np.maximum.accumulate(path)-path))
            features=[len(values)/window,*values.mean(axis=0),*values.std(axis=0),
                      *(values>0).mean(axis=0),float((net<0).mean()),drawdown]
            for horizon in (7,30):
                width=min(horizon,len(net));sums=np.convolve(net,np.ones(width),mode='valid')
                features.extend([float(sums.min()),float(np.quantile(sums,.1))])
            output.extend(features)
        output=np.asarray(output,dtype=float)
        if output.shape!=(52,) or not np.isfinite(output).all():raise ValueError('Неверные признаки длинной истории')
        return output


class LongPolicy(DiversePolicy):
    MODES=('extended','mean50')

    @staticmethod
    def score(row,mode):
        if mode=='extended':return row['extended_score']
        if mode=='mean50':return .5*(row['extended_score']+row['score25'])
        raise ValueError('Неверный режим31')

    @classmethod
    def choose(cls,rows):
        # Тот же проверенный ранний селектор; меняются только имена новой модели.
        mapped=[{**r,'cat_score':r['extended_score']} for r in rows]
        choice=DiversePolicy.choose(mapped)
        for trial in choice['trials']:
            if trial['mode']=='cat':trial['mode']='extended'
        if choice['selected']['mode']=='cat':choice['selected']['mode']='extended'
        return choice


class LongStudy(DiverseExperiment):
    PARAMS=CrossfitExperiment.PARAMS
    train_cutoff=CrossfitExperiment.train_cutoff

    def __init__(self, source, reference, output, dataset):
        super().__init__(source,reference,output)
        data=Dataset(dataset)
        cache={}
        for label,rows in (('train',self.train),('control',self.control)):
            for index,row in enumerate(rows):
                cutoff=row.get('as_of',row.get('cutoff'));key=(row['company'],cutoff)
                if key not in cache:
                    cache[key]=LongHistoryFeatures.make(row['company'],date.fromisoformat(cutoff),data.transactions[row['company']])
                if len(row['features'])!=34:raise ValueError('Изменилась схема21')
                row['features']=np.r_[row['features'],cache[key]].tolist()
                if (index+1)%2000==0:print(f'Long31 prepared {label} {index+1}',flush=True)
        with (output/'prepared.pickle').open('wb') as stream:pickle.dump({'train':self.train,'control':self.control},stream)
        started=json.loads((output/'started.json').read_text('utf-8'))
        started.update(code_sha256=digest(Path(__file__)),protocol_sha256=digest(Path('journal/31_long_history_risk.md')),
            dataset_sha256=digest(dataset),prepared86_sha256=digest(output/'prepared.pickle'),feature_count=86,
            diverse_helper_sha256=digest(Path('evaluation/liquidity_risk/diverse_risk.py')))
        write_json(output/'started.json',started)

    def predict(self,rows):
        CrossfitExperiment.predict(self,rows)
        for row in rows:row['extended_score']=row.pop('crossfit_score')

    @staticmethod
    def metrics31(rows,choice):
        labels=[r['label'] for r in rows]
        flags={name:[r[key] for r in rows] for name,key in
               (('candidate18','risk18'),('candidate21','risk21'),('candidate25','risk25'))}
        flags['current']=[r['current']>=.5 for r in rows]
        flags['selected31']=LongPolicy.flags(rows,choice)
        return {name:Score.classification(labels,values) for name,values in flags.items()}

    @staticmethod
    def bootstrap31(rows,choice,baseline):
        mapped=[{**r,'cat_score':r['extended_score']} for r in rows]
        choice={**choice,'mode':'cat' if choice['mode']=='extended' else choice['mode']}
        result=DiverseExperiment.bootstrap(mapped,choice,baseline)
        result['comparison']='selected31_minus_'+baseline
        return result

    def run(self):
        early=[r for r in self.control if r['phase'] in CrossfitPolicy.EARLY]
        self.predict(early);selection=LongPolicy.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        write_json(self.output/'selection-lock.json',{'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Frozen31: '+str(selection['selected']),flush=True)
        self.predict([r for r in self.control if r['phase'] not in CrossfitPolicy.EARLY])
        choice=selection['selected']
        report={'selection':selection,'independent_control':False,'production_activated':False,
                'probability_calibrated':False,'probability_any_negative':None,'phases':{},
                'total':self.metrics31(self.control,choice)}
        for phase in sorted({r['phase'] for r in self.control}):
            rows=[r for r in self.control if r['phase']==phase]
            report['phases'][phase]={'metrics':self.metrics31(rows,choice),
                'companies':len({r['company'] for r in rows}),
                'positive_companies':len({r['company'] for r in rows if r['label']}),
                'score_diagnostics':{mode:reliability([r['label'] for r in rows],[LongPolicy.score(r,mode) for r in rows]) for mode in LongPolicy.MODES},
                'diagnostic_fixed_policies':{mode:{str(t):Score.classification([r['label'] for r in rows],
                    LongPolicy.flags(rows,{'mode':mode,'threshold':t})) for t in CrossfitPolicy.THRESHOLDS} for mode in LongPolicy.MODES}}
        old,new=report['total']['candidate25'],report['total']['selected31']
        report['preliminary_improvement']=bool(choice['mode']!='keep25' and
            ((new['tp']>=old['tp'] and new['fp']<old['fp']) or (new['tp']>old['tp'] and new['fp']<=old['fp'])) and
            all(p['metrics']['selected31']['tp']>=p['metrics']['candidate25']['tp'] for p in report['phases'].values()))
        report['paired_company_bootstrap']={base:self.bootstrap31(self.control,choice,base) for base in ('risk25','risk21')}
        for mode in ('cutoff','company'):
            report['by_'+mode]={key:self.metrics31([r for r in self.control if r[mode]==key],choice) for key in sorted({r[mode] for r in self.control})}
        write_json(self.output/'predictions.json',[{k:v for k,v in r.items() if k!='features'} for r in self.control])
        write_json(self.output/'results.json',report)
        write_json(self.output/'completed.json',{'models':sum(len(m) for m in self.models.values()),
            'results_sha256':digest(self.output/'results.json'),'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Long31 complete: '+str(report['total']['selected31']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=Path('data/raw/rolling-peer-risk-v21'))
    parser.add_argument('--reference',type=Path,default=Path('data/raw/company-crossfit-v25'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/long-history-risk-v31'))
    args=parser.parse_args();LongStudy(args.source,args.reference,args.output,args.zip).run()
