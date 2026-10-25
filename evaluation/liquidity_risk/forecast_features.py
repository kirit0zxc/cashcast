"""Причинные прогнозы двух временных моделей как признаки условного резерва."""
import argparse
from datetime import date,timedelta
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

from .distribution_run import DistributionExperiment
from .distribution import DistributionQueries,DistributionModel,HORIZONS
from .weekly_reserve import WeeklyReserve
from .full_chronos import PHASES
from .chronos_trial import BalanceContext
from evaluation.fallback_model.data import Dataset
from app.modules.forecasting.service import get_forecast_service


class ForecastFeatures:
    @staticmethod
    def extend(row,chronos):
        scale=row['scale'];opening=row['opening_minor']
        if not np.isfinite(scale) or scale<=0:raise ValueError('Некорректная шкала')
        extra=[]
        for values in (row['current_interval'],chronos):
            values=np.asarray(values,dtype=float)
            if values.shape!=(30,3) or not np.isfinite(values).all():raise ValueError('Некорректные прогнозные квантили')
            normalized=(values-opening)/scale
            for horizon in HORIZONS:
                extra.extend(np.min(normalized[:horizon],axis=0))
                extra.extend(normalized[horizon-1])
        probability=row['current']
        if probability is not None and (not np.isfinite(probability) or not 0<=probability<=1):
            raise ValueError('Некорректная вероятность текущей модели')
        extra.extend([0 if probability is None else probability,float(probability is None),float(row['fallback'])])
        return np.r_[row['base_features'],extra]


class ForecastPreparation:
    def __init__(self,source,reference,output):
        self.data=Dataset(source);self.reference=reference;self.output=output
        output.mkdir(parents=True,exist_ok=True)
        self.metadata={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                       'target_end':'2025-12-31','zero_shot_chronos_only':True}

    def save(self,name,value):
        with (self.output/name).open('wb') as stream:pickle.dump(value,stream)

    @staticmethod
    def make(snapshot,truth,current_interval,probability,context):
        row=DistributionExperiment.make(snapshot,truth)
        row['base_features']=row.pop('features')
        row.update(opening_minor=snapshot.opening_balance_minor,current_interval=current_interval,
                   current=probability,context=context,fallback=context is None)
        return row

    def prepare(self):
        dates=[];day=date(2024,12,31)
        while day+timedelta(days=30)<=date(2025,12,31):dates.append(day);day+=timedelta(days=14)
        windows,excluded=self.data.windows(dates,date(2025,12,31))
        train=[]
        for index,(snapshot,truth,_) in enumerate(windows):
            current=get_forecast_service().run(snapshot)
            if current.model_version!='seasonal-estimated-2.1-w84':raise ValueError('Другой текущий движок')
            interval=np.array([[p.balance_p10_minor,p.balance_p50_minor,p.balance_p90_minor] for p in current.points])
            row=self.make(snapshot,truth,interval,current.risk.probability_any_negative,BalanceContext.make(snapshot))
            if row['history_days']>=28:train.append(row)
            if (index+1)%250==0:print(f'Prepared forecast train {index+1}/{len(windows)}',flush=True)
        self.save('prepared-train.pickle',train)
        self.metadata.update(train_windows=len(train),excluded=excluded)
        for phase,args in PHASES.items():
            windows,_=self.data.windows(*args)
            with (self.reference/f'inferred-{phase}.pickle').open('rb') as stream:cached=pickle.load(stream)['rows']
            lookup={(r['company'],r['cutoff']):r for r in cached}
            rows=[]
            for snapshot,truth,_ in windows:
                original=lookup[(snapshot.account_id,str(snapshot.as_of))]
                np.testing.assert_array_equal(truth,original['truth'])
                row=self.make(snapshot,truth,original['intervals']['current'],original['probability'],None)
                row['fallback']=original['fallback']
                row['features']=ForecastFeatures.extend(row,original['intervals']['balance365'])
                if row['opening']>=0 and row['current'] is not None:rows.append(row)
            self.save(f'features-{phase}.pickle',rows)
            print(f'Prepared forecast features {phase}',flush=True)
        (self.output/'sources.json').write_text(json.dumps(self.metadata,indent=2),encoding='utf-8')

    @staticmethod
    def infer(output,model_info):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4);torch.manual_seed(20261024)
        source=json.loads(model_info.read_text(encoding='utf-8'))
        if source['revision']!='29ec3766d36d6f73f0696f85560a422f50e8498c':raise ValueError('Другой Chronos')
        with (output/'prepared-train.pickle').open('rb') as stream:rows=pickle.load(stream)
        indexes=[i for i,r in enumerate(rows) if not r['fallback']]
        inputs=[rows[i]['context'][0].astype(np.float32)[None,:] for i in indexes]
        pipeline=Chronos2Pipeline.from_pretrained(source['snapshot'],device_map='cpu',local_files_only=True)
        forecasts,_=pipeline.predict_quantiles(inputs,prediction_length=30,quantile_levels=[.1,.5,.9],
                            batch_size=16,context_length=365,cross_learning=False)
        for i,tensor in zip(indexes,forecasts,strict=True):
            row=rows[i]
            values=np.sort(tensor.detach().cpu().numpy()[0]*row['context'][1]+row['opening_minor'],axis=1)
            row['features']=ForecastFeatures.extend(row,values)
        for row in rows:
            if row['fallback']:row['features']=ForecastFeatures.extend(row,row['current_interval'])
            del row['context']
        with (output/'features-train.pickle').open('wb') as stream:pickle.dump(rows,stream)
        print(f'Zero-shot forecast train features ready: {len(rows)}',flush=True)


class ForecastReserve(WeeklyReserve):
    NAME='forecast6'

    def __init__(self,output):
        self.output=output;self.models={}
        self.report={'sources':json.loads((output/'sources.json').read_text()),'production_activated':False,
                     'calibrated':False,'independent_control':False}

    def load(self,phase):
        with (self.output/f'features-{phase}.pickle').open('rb') as stream:return pickle.load(stream)

    def train(self):
        from catboost import CatBoostClassifier
        rows=self.load('train');natural=[r for r in rows if r['opening']>=0]
        self.priors={str(h):(sum(np.any(r['truth'][:h,2]<0) for r in natural)+.5)/(len(natural)+1) for h in HORIZONS}
        x,y,w=DistributionQueries.augment(rows)
        self.report['train']={'windows':len(rows),'queries':len(y),'features':x.shape[1],'target_end':'2025-12-31',
                             'companies':len({r['company'] for r in rows}),'priors':self.priors}
        self.write('results.json',self.report)
        model=DistributionModel(6).fit(x,y,w);model.model.save_model(str(self.output/f'{self.NAME}.cbm'))
        self.models[self.NAME]=model
        old=DistributionModel(6);old.model=CatBoostClassifier();old.model.load_model(str(self.output.parent/'reserve-distribution-v9/cdf6.cbm'))
        self.models['cdf6']=old
        print('Forecast-informed reserve trained',flush=True)

    def prepare(self,phase):
        rows=self.load(phase)
        for row in rows:row['scores']={}
        for horizon in HORIZONS:
            for name,model in self.models.items():
                column='base_features' if name=='cdf6' else 'features'
                queries=[DistributionQueries.query(r[column],horizon,r['opening']) for r in rows]
                for row,p in zip(rows,model.predict(queries),strict=True):row['scores'].setdefault(name,{})[str(horizon)]=float(p)
        return rows,{}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','infer','train'))
    parser.add_argument('--zip',type=Path)
    parser.add_argument('--reference',type=Path,default=Path('data/raw/chronos-specialists-v8'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/forecast-reserve-v18'))
    parser.add_argument('--model-info',type=Path,default=Path('journal/chronos-source.json'))
    args=parser.parse_args()
    if args.stage=='prepare':
        if args.zip is None:parser.error('ДляprepareнуженZIP')
        ForecastPreparation(args.zip,args.reference,args.output).prepare()
    elif args.stage=='infer':ForecastPreparation.infer(args.output,args.model_info)
    else:ForecastReserve(args.output).run()
