"""Обучаемые суммы блоков с причинным дневным профилем текущей модели."""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import pickle

import numpy as np

from evaluation.fallback_model.data import Dataset
from .forecast_features import ForecastPreparation
from .full_chronos import PHASES
from .horizon_ensemble import HorizonWeights
from .research_audit import cash_metrics, cluster_intervals, deltas, digest, write_json


class BlockMath:
    BLOCKS = ((0, 7), (7, 14), (14, 30))
    ALPHAS = (.25, .5, 1.)
    OBJECTIVE = ('inflow_mae_rub', 'outflow_mae_rub', 'inflow_total_mae_rub', 'outflow_total_mae_rub')
    GUARDS = ('inflow_rmse_rub', 'outflow_rmse_rub', 'inflow_total_rmse_rub', 'outflow_total_rmse_rub',
              'inflow_total_mae_rub', 'outflow_total_mae_rub')

    @classmethod
    def features(cls, row):
        base = np.asarray(row['base_features'], dtype=float)
        if base.shape != (93,) or not np.isfinite(base).all():
            raise ValueError('Нужны93конечных признака прошлого')
        cutoff = date.fromisoformat(row['cutoff'])
        output = []
        for start, end in cls.BLOCKS:
            days = [cutoff+timedelta(days=h) for h in range(start+1, end+1)]
            weekdays = np.bincount([d.weekday() for d in days], minlength=7)/(end-start)
            output.append(np.r_[base, start, end-start, days[-1].month, days[-1].day, weekdays])
        return np.asarray(output)

    @classmethod
    def training(cls, rows):
        if any(Dataset.heldout(r['company']) or date.fromisoformat(r['cutoff'])+timedelta(days=37)>date(2025,12,31) for r in rows):
            raise ValueError('Нарушена граница обучающих компаний/времени')
        counts = Counter(r['company'] for r in rows)
        x, y, w = [], [], []
        for row in rows:
            features = np.asarray(row['features'])
            if features.shape != (132,): raise ValueError('Изменилась схема18')
            np.testing.assert_array_equal(features[:93], row['base_features'])
            scale = row['scale']
            truth = np.asarray(row['truth'])
            if not np.isfinite(scale) or scale <= 0 or truth.shape != (30,3) or not np.isfinite(truth).all() or np.any(truth[:,:2]<0):
                raise ValueError('Некорректная обучающая цель/масштаб')
            x.extend(cls.features(row))
            for start, end in cls.BLOCKS:
                y.append(truth[start:end,:2].sum(axis=0)/(scale*(end-start)))
                w.append(scale*(end-start)/counts[row['company']])
        weights = np.asarray(w); weights /= weights.mean()
        return np.asarray(x), np.asarray(y), weights

    @staticmethod
    def allocate(total, profile):
        profile = np.asarray(profile, dtype=float)
        if profile.ndim != 1 or not len(profile) or not np.isfinite(profile).all() or np.any(profile<0):
            raise ValueError('Непригодный дневной профиль')
        if not np.isfinite(total) or total < 0 or total > 9e15: raise ValueError('Недопустимая сумма')
        total = int(round(float(total)))
        fractions = profile/profile.sum() if profile.sum() else np.full(len(profile),1/len(profile))
        ideal = fractions*total
        result = np.floor(ideal).astype(np.int64)
        remainder = total-int(result.sum())
        if not 0 <= remainder <= len(profile): raise ValueError('Потеря точности при распределении суммы')
        order = np.argsort(-(ideal-result), kind='stable')
        result[order[:remainder]] += 1
        assert int(result.sum()) == total and np.all(result>=0)
        return result

    @classmethod
    def predict(cls, row, predicted, scale, alpha):
        if alpha not in cls.ALPHAS: raise ValueError('Незарегистрированная смесь')
        if row['fallback']: return row['models']['current'].copy()
        predicted = np.asarray(predicted, dtype=float)
        if predicted.shape != (3,2) or not np.isfinite(predicted).all() or not np.isfinite(scale) or scale<=0:
            raise ValueError('Неверные предсказания блоков')
        current = row['models']['current'][:,:2]
        flows = np.zeros((30,2), dtype=np.int64)
        for i, (start, end) in enumerate(cls.BLOCKS):
            for channel in range(2):
                total = max(0.,predicted[i,channel])*scale*(end-start)
                flows[start:end,channel] = cls.allocate(total,current[start:end,channel])
        flows = np.rint((1-alpha)*current+alpha*flows).astype(np.int64)
        result = np.column_stack([flows, row['opening']+np.cumsum(flows[:,0]-flows[:,1])])
        if np.max(abs(result))>9e15: raise ValueError('Денежный бюджет превышен')
        return result

    @staticmethod
    def macro(rows, model, horizon, channel):
        groups = {}
        for row in rows:
            groups.setdefault(row['company'],[]).append(float(np.abs(
                row['models'][model][:horizon,channel]-row['truth'][:horizon,channel]).mean()))
        return float(np.mean([np.mean(v) for v in groups.values()]))

    @classmethod
    def choose(cls, rows):
        if not rows or any(Dataset.heldout(r['company']) or r['cutoff'] not in ('2026-01-31','2026-02-28','2026-03-31') for r in rows):
            raise ValueError('Выбор толькораннийdevelopment')
        names = ('current', *(f'block{a}' for a in cls.ALPHAS))
        scores = {m:{str(h):cash_metrics(rows,m,h) for h in (7,14,30)} for m in names}
        trials = [{'model':'current','alpha':None,'objective':1.,'eligible':True}]
        for alpha in cls.ALPHAS:
            name = f'block{alpha}'
            ratios = [scores[name][str(h)][k]/max(scores['current'][str(h)][k],1e-12)
                      if scores[name][str(h)][k] or scores['current'][str(h)][k] else 1.
                      for h in (7,14,30) for k in cls.OBJECTIVE]
            objective = float(np.mean(ratios)); eligible = objective <= .99
            for h in (7,14,30):
                base, new = scores['current'][str(h)], scores[name][str(h)]
                eligible &= all(new[k]<=base[k]*1.05 for k in cls.GUARDS)
                eligible &= all(new[k]<=base[k]*1.02 for k in ('inflow_mae_rub','outflow_mae_rub'))
                eligible &= all(cls.macro(rows,name,h,c)<=cls.macro(rows,'current',h,c)*1.02 for c in (0,1))
                for cutoff in sorted({r['cutoff'] for r in rows}):
                    group = [r for r in rows if r['cutoff']==cutoff]
                    b,n = cash_metrics(group,'current',h),cash_metrics(group,name,h)
                    eligible &= all(n[k]<=b[k]*1.05 for k in ('inflow_mae_rub','outflow_mae_rub'))
            trials.append({'model':name,'alpha':alpha,'objective':objective,'eligible':bool(eligible)})
        selected = min((t for t in trials if t['eligible']),key=lambda t:(t['objective'],t['alpha'] is not None,t['alpha'] or 0))
        return {'selected':selected,'trials':trials,'scores':scores,'selection':'development January-March only'}


class BlockStudy:
    PARAMS = dict(iterations=500,depth=5,learning_rate=.04,l2_leaf_reg=10,loss_function='MAE',
                  random_seed=20261025,thread_count=4,verbose=False,allow_writing_files=False)

    def __init__(self, source, output):
        if output.exists(): raise FileExistsError('Каталог существует; проверить процесс, не дублировать')
        if digest(source)!='e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987':
            raise ValueError('Другой организаторский датасет')
        output.mkdir(parents=True); self.output=output; self.data=Dataset(source)
        self.sources={'dataset':digest(source),'code':digest(Path(__file__)),'protocol':digest(Path('journal/30_block_flows.md'))}

    def train(self):
        from catboost import CatBoostRegressor
        path = Path('data/raw/forecast-reserve-v18/features-train.pickle')
        expected = json.loads(Path('research_handoff/results/26/results.json').read_text('utf-8'))['sources_sha256']['training_cache']
        if digest(path)!=expected: raise ValueError('Изменились обучающие признаки18')
        with path.open('rb') as stream: rows=pickle.load(stream)
        x,y,w = BlockMath.training(rows); self.models=[]
        self.sources['training_cache']=digest(path)
        write_json(self.output/'started.json',{'params':self.PARAMS,'sources_sha256':self.sources,
            'windows':len(rows),'rows_per_model':len(y),'companies':len({r['company'] for r in rows}),
            'heldout_excluded':True,'max_confirmation':str(max(date.fromisoformat(r['cutoff'])+timedelta(days=37) for r in rows)),
            'sample_weights_sha256':__import__('hashlib').sha256(w.tobytes()).hexdigest()})
        for channel in range(2):
            model=CatBoostRegressor(**self.PARAMS);model.fit(x,y[:,channel],sample_weight=w)
            target=self.output/f'block-{channel}.cbm';model.save_model(str(target))
            loaded=CatBoostRegressor();loaded.load_model(str(target))
            np.testing.assert_allclose(model.predict(x[:30]),loaded.predict(x[:30]),rtol=0,atol=1e-12)
            self.models.append(loaded);self.sources[f'weights_{channel}']=digest(target)
            print(f'Block30 trained channel{channel}',flush=True)

    def infer(self, phase):
        path=Path('data/raw/chronos-specialists-v8')/f'inferred-{phase}.pickle'
        with path.open('rb') as stream: rows=pickle.load(stream)['rows']
        self.sources['cache_'+phase]=digest(path)
        windows,_=self.data.windows(*PHASES[phase]);lookup={(s.account_id,str(s.as_of)):(s,t) for s,t,_ in windows}
        if len(lookup)!=len(rows): raise ValueError('Изменился состав оценки')
        for row in rows:
            snapshot,truth=lookup[(row['company'],row['cutoff'])]
            np.testing.assert_array_equal(truth,row['truth'])
            values=np.stack([row['models'][m][:,2] for m in ('current','direct','balance365')],axis=1)[None]
            row['models']['candidate18']=row['models']['current'].copy()
            row['models']['candidate18'][:,2]=HorizonWeights.predict(values,0.,(.5,1.,.75))[0]
            row['models']['benchmark75_25']=row['models']['blend75'].copy()
            if row['fallback']:
                for a in BlockMath.ALPHAS: row['models'][f'block{a}']=row['models']['current'].copy()
                continue
            features=ForecastPreparation.make(snapshot,truth,row['intervals']['current'],row['probability'],None)
            x=BlockMath.features(features)
            predictions=np.stack([model.predict(x,thread_count=4) for model in self.models],axis=1)
            for a in BlockMath.ALPHAS:
                row['models'][f'block{a}']=BlockMath.predict(row,predictions,features['scale'],a)
        print(f'Block30 inferred {phase} {len(rows)}',flush=True)
        return rows

    def run(self):
        self.train()
        early=self.infer('validation');selection=BlockMath.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        write_json(self.output/'selection-lock.json',{'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Frozen30: '+str(selection['selected']),flush=True)
        phases={'validation':early}
        for phase in PHASES:
            if phase!='validation':phases[phase]=self.infer(phase)
        models=('current','benchmark75_25','candidate18',*(f'block{a}' for a in BlockMath.ALPHAS),'selected30')
        report={'selection':selection,'independent_control':False,'production_activated':False,
                'risk_unchanged':'18/21/25/29','phases':{},'sources_sha256':self.sources}
        details={}
        for phase,rows in phases.items():
            for row in rows:row['models']['selected30']=row['models'][selection['selected']['model']].copy()
            with (self.output/f'inferred-{phase}.pickle').open('wb') as stream:pickle.dump(rows,stream)
            report['phases'][phase]={'scores':{m:{str(h):cash_metrics(rows,m,h) for h in (7,14,30)} for m in models},
                'deltas':{base:{str(h):deltas(cash_metrics(rows,'selected30',h),cash_metrics(rows,base,h)) for h in (7,14,30)}
                          for base in ('current','benchmark75_25','candidate18')},
                'cluster_intervals':{str(h):cluster_intervals(rows,'selected30','current',h) for h in (7,14,30)}}
            details[phase]={mode:{key:{m:{str(h):cash_metrics([r for r in rows if r[mode]==key],m,h) for h in (7,14,30)}
                for m in models} for key in sorted({r[mode] for r in rows})} for mode in ('company','cutoff')}
        keys=tuple(set(BlockMath.OBJECTIVE+BlockMath.GUARDS))
        report['preliminary_transfer']=bool(selection['selected']['alpha'] is not None and all(
            p['scores']['selected30'][str(h)][k]<=p['scores']['current'][str(h)][k]*1.05
            for phase,p in report['phases'].items() if phase!='validation' for h in (7,14,30) for k in keys))
        write_json(self.output/'results.json',report);write_json(self.output/'by-company-and-period.json',details)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json')})
        print('Block30 complete; preliminary_transfer='+str(report['preliminary_transfer']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/raw/block-flows-v30'))
    args=parser.parse_args();BlockStudy(args.zip,args.output).run()
