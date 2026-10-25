"""Малая коррекция zero-shotChronos, обученная на причинных прогнозах прошлого."""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import pickle

import numpy as np

from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from .forecast_features import ForecastFeatures, ForecastPreparation
from .full_chronos import PHASES
from .horizon_ensemble import HorizonWeights
from .research_audit import cash_metrics, cluster_intervals, digest, write_json


class ResidualMath:
    HORIZONS=(7,14,30)
    ALPHAS=(0.,.25,.5,1.)
    END_MEDIAN=(115,121,127)

    @staticmethod
    def features(row):
        values=np.asarray(row['features'],dtype=float)
        if values.shape!=(132,) or not np.isfinite(values).all():
            raise ValueError('Нужна закреплённая схема132признаков18')
        return np.stack([np.r_[values,h/30.] for h in ResidualMath.HORIZONS])

    @classmethod
    def training(cls,rows):
        if any(Dataset.heldout(r['company']) or date.fromisoformat(r['cutoff'])+timedelta(days=37)>date(2025,12,31) for r in rows):
            raise ValueError('Нарушена граница обучающих компаний/времени')
        counts=Counter(r['company'] for r in rows)
        x,y,w=[],[],[]
        for row in rows:
            scale=row['scale']
            if not np.isfinite(scale) or scale<=0:raise ValueError('Непригодный масштаб')
            x.extend(cls.features(row))
            for h,index in zip(cls.HORIZONS,cls.END_MEDIAN,strict=True):
                y.append((row['truth'][h-1,2]-row['opening_minor']-row['features'][index]*scale)/(scale*h))
                w.append(scale*h/counts[row['company']])
        weights=np.asarray(w);weights/=weights.mean()
        return np.asarray(x),np.asarray(y),weights

    @classmethod
    def correct(cls,row,residual,scale,alpha):
        if alpha not in cls.ALPHAS:raise ValueError('Незарегистрированный вес')
        if row['fallback']:return row['models']['current'].copy()
        residual=np.asarray(residual,dtype=float)
        if residual.shape!=(3,) or not np.isfinite(residual).all() or not np.isfinite(scale) or scale<=0:
            raise ValueError('Непригодная коррекция')
        correction=np.interp(np.arange(1,31),(0,*cls.HORIZONS),np.r_[0.,residual*scale*np.asarray(cls.HORIZONS)])
        balance=row['models']['balance365'][:,2]+alpha*correction
        if not np.isfinite(balance).all() or np.max(abs(balance))>9e15:raise ValueError('Денежный бюджет превышен')
        result=row['models']['current'].copy()
        result[:,2]=np.rint(balance).astype(np.int64)
        return result

    @classmethod
    def choose(cls,rows):
        if not rows or any(Dataset.heldout(r['company']) or r['cutoff'] not in ('2026-01-31','2026-02-28','2026-03-31') for r in rows):
            raise ValueError('Выбор разрешён только на development январь–март')
        scores={name:{str(h):Score.summarize(rows,name,h) for h in cls.HORIZONS}
                for name in ('candidate18','blend75',*(f'residual{a}' for a in cls.ALPHAS))}
        base=scores['candidate18']
        trials=[{'model':'candidate18','alpha':None,'objective':1.,'eligible':True}]
        for alpha in cls.ALPHAS:
            name=f'residual{alpha}';score=scores[name]
            objective=float(np.mean([score[str(h)]['mae_rub']/base[str(h)]['mae_rub'] for h in cls.HORIZONS]))
            eligible=objective<=.99
            for h in map(str,cls.HORIZONS):
                for baseline in ('candidate18','blend75'):
                    for metric in ('mae_rub','rmse_rub'):
                        eligible &= score[h][metric]<=scores[baseline][h][metric]*1.02
                eligible &= score[h]['company_macro_mae_rub']<=base[h]['company_macro_mae_rub']*1.02
                eligible &= all(value<=base[h]['cutoff_mae_rub'][cutoff]*1.05 for cutoff,value in score[h]['cutoff_mae_rub'].items())
            trials.append({'model':name,'alpha':alpha,'objective':objective,'eligible':bool(eligible)})
        selected=min((r for r in trials if r['eligible']),key=lambda r:(r['objective'],r['alpha'] is not None,r['alpha'] or 0))
        return {'selected':selected,'trials':trials,'scores':scores,'selection':'development January-March only'}


class ResidualExperiment:
    PARAMS=dict(loss_function='MAE',iterations=400,depth=4,learning_rate=.04,l2_leaf_reg=8,
                random_seed=20261025,thread_count=4,verbose=False,allow_writing_files=False)

    def __init__(self,source,output):
        if output.exists():raise FileExistsError('Каталог уже существует; сначала проверить процесс')
        output.mkdir(parents=True)
        self.data=Dataset(source);self.output=output
        self.cache=Path('data/raw/chronos-specialists-v8')
        self.sources={'dataset':digest(source),'code':digest(Path(__file__)),
                      'protocol':digest(Path('journal/26_chronos_residual.md'))}

    def train(self):
        from catboost import CatBoostRegressor
        path=Path('data/raw/forecast-reserve-v18/features-train.pickle')
        with path.open('rb') as stream:rows=pickle.load(stream)
        self.sources['training_cache']=digest(path)
        x,y,weights=ResidualMath.training(rows)
        write_json(self.output/'started.json',{'params':self.PARAMS,'sources_sha256':self.sources,
            'windows':len(rows),'training_rows':len(y),'companies':len({r['company'] for r in rows}),
            'max_target_confirmation':str(max(date.fromisoformat(r['cutoff'])+timedelta(days=37) for r in rows)),
            'heldout_excluded':True,'zero_shot_only':True})
        self.model=CatBoostRegressor(**self.PARAMS);self.model.fit(x,y,sample_weight=weights)
        self.model.save_model(str(self.output/'residual.cbm'))
        loaded=CatBoostRegressor();loaded.load_model(str(self.output/'residual.cbm'))
        np.testing.assert_allclose(self.model.predict(x[:30]),loaded.predict(x[:30]),rtol=0,atol=1e-12)
        self.model=loaded
        print('Residual26 trained and reload verified',flush=True)

    def infer(self,phase):
        path=self.cache/f'inferred-{phase}.pickle'
        with path.open('rb') as stream:rows=pickle.load(stream)['rows']
        self.sources['cache_'+phase]=digest(path)
        windows,_=self.data.windows(*PHASES[phase])
        lookup={(s.account_id,str(s.as_of)):(s,t) for s,t,_ in windows}
        if len(rows)!=len(lookup):raise ValueError('Изменился состав оценки')
        supported=[];features=[]
        for row in rows:
            snapshot,truth=lookup[(row['company'],row['cutoff'])]
            np.testing.assert_array_equal(truth,row['truth'])
            values=np.stack([row['models'][n][:,2] for n in ('current','direct','balance365')],axis=1)[None]
            row['models']['candidate18']=row['models']['current'].copy()
            row['models']['candidate18'][:,2]=HorizonWeights.predict(values,0.,(.5,1.,.75))[0]
            if row['fallback']:
                for alpha in ResidualMath.ALPHAS:row['models'][f'residual{alpha}']=row['models']['current'].copy()
                continue
            feature=ForecastPreparation.make(snapshot,truth,row['intervals']['current'],row['probability'],None)
            feature['fallback']=False
            feature['features']=ForecastFeatures.extend(feature,row['intervals']['balance365'])
            supported.append((row,feature['scale']))
            features.extend(ResidualMath.features(feature))
        if supported:
            residuals=self.model.predict(np.asarray(features)).reshape(-1,3)
            for (row,scale),residual in zip(supported,residuals,strict=True):
                for alpha in ResidualMath.ALPHAS:
                    row['models'][f'residual{alpha}']=ResidualMath.correct(row,residual,scale,alpha)
        with (self.output/f'inferred-{phase}.pickle').open('wb') as stream:pickle.dump(rows,stream)
        print('Residual26 inferred '+phase,flush=True)
        return rows

    def run(self):
        self.train()
        early=self.infer('validation')
        selection=ResidualMath.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        print('Frozen residual26 '+str(selection['selected']),flush=True)
        phases={'validation':early}
        for phase in PHASES:
            if phase!='validation':phases[phase]=self.infer(phase)
        self.score(self.output,selection,phases,self.sources)

    @staticmethod
    def score(output,selection,phases,sources):
        name=selection['selected']['model'];report={'selection':selection,'phases':{},
            'independent_control':False,'probability_calibrated':False,'risk_unchanged':'18/21',
            'flows_unchanged':'native_current','point_is_not_native_flow_sum':True,'production_activated':False}
        details={}
        for phase,rows in phases.items():
            for row in rows:
                row['models']['selected26']=row['models'][name]
                row['models']['benchmark75_25']=row['models']['blend75']
            models=('current','benchmark75_25','candidate18','selected26',*(f'residual{a}' for a in ResidualMath.ALPHAS))
            report['phases'][phase]={'scores':{m:{str(h):cash_metrics(rows,m,h) for h in ResidualMath.HORIZONS} for m in models},
                'cluster_intervals':{str(h):cluster_intervals(rows,'selected26','candidate18',h) for h in ResidualMath.HORIZONS}}
            details[phase]={}
            for mode in ('cutoff','company'):
                details[phase][mode]={key:{m:{str(h):cash_metrics([r for r in rows if r[mode]==key],m,h)
                    for h in ResidualMath.HORIZONS} for m in models} for key in sorted({r[mode] for r in rows})}
        report['preliminary_transfer']=bool(name!='candidate18' and all(
            p['scores']['selected26'][str(h)][metric]<=p['scores']['candidate18'][str(h)][metric]*1.05
            for p in report['phases'].values() for h in ResidualMath.HORIZONS for metric in ('balance_mae_rub','balance_rmse_rub')) and all(
            np.mean([report['phases'][p]['scores']['selected26'][str(h)]['balance_mae_rub']/report['phases'][p]['scores']['candidate18'][str(h)]['balance_mae_rub']
                for h in ResidualMath.HORIZONS])<1 for p in ('late_development','other_early','late_other')))
        report['sources_sha256']=sources;report['weights_sha256']=digest(output/'residual.cbm')
        report['reporting_source_sha256']=digest(Path(__file__))
        write_json(output/'results.json',report);write_json(output/'by-company-and-period.json',details)
        write_json(output/'completed.json',{'results_sha256':digest(output/'results.json')})
        print(json.dumps({'selected':selection['selected'],'preliminary_transfer':report['preliminary_transfer']},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path)
    parser.add_argument('--output',type=Path,default=Path('data/raw/chronos-residual-v26'))
    parser.add_argument('--score-only',action='store_true')
    args=parser.parse_args()
    if args.score_only:
        selection=json.loads((args.output/'selection-frozen.json').read_text('utf-8'))
        original=json.loads((args.output/'results.json').read_text('utf-8'))
        phases={}
        for phase in PHASES:
            with (args.output/f'inferred-{phase}.pickle').open('rb') as stream:phases[phase]=pickle.load(stream)
        ResidualExperiment.score(args.output,selection,phases,original['sources_sha256'])
    else:
        if args.zip is None:parser.error('--zip обязателен для обучения')
        ResidualExperiment(args.zip,args.output).run()
