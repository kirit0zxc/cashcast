"""Согласование с большим изменением исторически более шумного потока."""
import argparse
from datetime import date, timedelta
from pathlib import Path
import pickle

import numpy as np

from evaluation.fallback_model.data import Dataset
from .full_chronos import PHASES
from .horizon_ensemble import HorizonWeights
from .research_audit import cash_metrics, cluster_intervals, deltas, digest, write_json
from .specialists import SpecialistMath


class WeightedReconciliation:
    @staticmethod
    def variances(context,scale,cutoff):
        past=np.asarray(context,dtype=float)
        if past.ndim!=2 or past.shape[0]!=2 or past.shape[1]<28 or not np.isfinite(past).all() or np.any(past<0) or not np.isfinite(scale) or scale<=0:
            raise ValueError('Нужна конечная неотрицательная прошлая история >=28дней')
        past=past[:,-84:].T*scale
        weekdays=np.array([(cutoff-timedelta(days=len(past)-1-i)).weekday() for i in range(len(past))])
        global_variance=past.var(axis=0)
        result=[]
        for h in range(1,31):
            group=past[weekdays==(cutoff+timedelta(days=h)).weekday()]
            result.append(np.maximum((len(group)*group.var(axis=0)+14*global_variance)/(len(group)+14),10_000.))
        return np.asarray(result)

    @staticmethod
    def project(flows,balances,opening,variances):
        flows=np.asarray(flows,dtype=float);balances=np.asarray(balances);variances=np.asarray(variances,dtype=float)
        if flows.shape!=(30,2) or balances.shape!=(30,) or variances.shape!=(30,2):raise ValueError('Неверная форма')
        if not all(np.isfinite(x).all() for x in (flows,balances,variances)) or np.any(flows<0) or np.any(variances<=0):
            raise ValueError('Неверные денежные величины/дисперсии')
        if np.max(abs(balances))>9e15 or np.max(flows)>9e15 or abs(opening)>9e15:raise ValueError('Превышен денежный бюджет')
        target=np.rint(balances).astype(np.int64);change=np.diff(target,prepend=int(opening))
        weight=variances[:,0]/variances.sum(axis=1)
        incoming=np.maximum.reduce([np.zeros(30),change.astype(float),flows[:,0]+weight*(change-flows[:,0]+flows[:,1])])
        incoming=np.rint(incoming).astype(np.int64);outgoing=incoming-change
        if np.max(incoming)>9e15 or np.max(outgoing)>9e15:raise ValueError('Согласование превысило денежный бюджет')
        return np.column_stack([incoming,outgoing,target])

    @staticmethod
    def choose(rows):
        if not rows or any(Dataset.heldout(r['company']) or r['cutoff'] not in ('2026-01-31','2026-02-28','2026-03-31') for r in rows):
            raise ValueError('Только ранний development')
        scores={m:{str(h):cash_metrics(rows,m,h) for h in (7,14,30)} for m in ('current','equal','weighted')}
        objective_keys=('inflow_mae_rub','outflow_mae_rub','inflow_total_mae_rub','outflow_total_mae_rub')
        guard_keys=('inflow_rmse_rub','outflow_rmse_rub','inflow_total_rmse_rub','outflow_total_rmse_rub','inflow_total_mae_rub','outflow_total_mae_rub')
        def ratio(new,old):
            return new/max(old,1e-12) if new or old else 1.
        objective=float(np.mean([ratio(scores['weighted'][str(h)][k],scores['current'][str(h)][k]) for h in (7,14,30) for k in objective_keys]))
        eligible=objective<=.99 and all(scores['weighted'][str(h)][k]<=scores['current'][str(h)][k]*1.05 for h in (7,14,30) for k in guard_keys)
        for cutoff in sorted({r['cutoff'] for r in rows}):
            group=[r for r in rows if r['cutoff']==cutoff]
            for h in (7,14,30):
                current=cash_metrics(group,'current',h);weighted=cash_metrics(group,'weighted',h)
                eligible &= all(weighted[k]<=current[k]*1.05 for k in ('inflow_mae_rub','outflow_mae_rub'))
        return {'selected':'weighted' if eligible else 'keep_current','objective':objective,'eligible':bool(eligible),
                'scores':scores,'selection':'development January-March only'}


class WeightedStudy:
    def __init__(self,output):
        if output.exists():raise FileExistsError('Каталог уже существует; сначала проверить процесс')
        output.mkdir(parents=True);self.output=output;self.sources={}

    def infer(self,phase):
        cache=Path('data/raw/chronos-specialists-v8')
        with (cache/f'inferred-{phase}.pickle').open('rb') as stream:rows=pickle.load(stream)['rows']
        with (cache/f'prepared-{phase}.pickle').open('rb') as stream:prepared=pickle.load(stream)['rows']
        if [(r['company'],r['cutoff']) for r in rows]!=[(r['company'],r['cutoff']) for r in prepared]:raise ValueError('Разошлись окна')
        for row,past in zip(rows,prepared,strict=True):
            np.testing.assert_array_equal(row['truth'],past['truth'])
            np.testing.assert_array_equal(row['models']['current'],past['models']['current'])
            values=np.stack([row['models'][m][:,2] for m in ('current','direct','balance365')],axis=1)[None]
            balance=HorizonWeights.predict(values,0.,(.5,1.,.75))[0]
            row['models']['candidate18']=row['models']['current'].copy();row['models']['candidate18'][:,2]=balance
            row['models']['benchmark75_25']=row['models']['blend75'].copy()
            flows=row['models']['current'][:,:2]
            row['models']['equal']=SpecialistMath.reconcile(flows,balance,row['opening'])
            if row['fallback']:
                row['models']['weighted']=row['models']['current'].copy()
            else:
                variance=WeightedReconciliation.variances(*past['contexts']['flow365'],date.fromisoformat(row['cutoff']))
                row['models']['weighted']=WeightedReconciliation.project(flows,balance,row['opening'],variance)
                predicted=row['models']['weighted']
                np.testing.assert_array_equal(predicted[:,2],row['opening']+np.cumsum(predicted[:,0]-predicted[:,1]))
        for stage in ('inferred','prepared'):self.sources[f'{stage}-{phase}']=digest(cache/f'{stage}-{phase}.pickle')
        with (self.output/f'inferred-{phase}.pickle').open('wb') as stream:pickle.dump(rows,stream)
        return rows

    def run(self):
        write_json(self.output/'started.json',{'code_sha256':digest(Path(__file__)),'protocol_sha256':digest(Path('journal/27_weighted_reconciliation.md'))})
        early=self.infer('validation');selection=WeightedReconciliation.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        print('Frozen weighted reconciliation: '+str({k:v for k,v in selection.items() if k!='scores'}),flush=True)
        phases={'validation':early}
        for phase in PHASES:
            if phase!='validation':phases[phase]=self.infer(phase)
        models=('current','benchmark75_25','candidate18','equal','weighted')
        report={'selection':selection,'independent_control':False,'production_activated':False,'phases':{},'risk_unchanged':'18/21/25'}
        details={}
        for phase,rows in phases.items():
            report['phases'][phase]={'scores':{m:{str(h):cash_metrics(rows,m,h) for h in (7,14,30)} for m in models},
                'deltas':{m:{str(h):deltas(cash_metrics(rows,'weighted',h),cash_metrics(rows,m,h)) for h in (7,14,30)} for m in ('current','equal')},
                'cluster_intervals':{str(h):cluster_intervals(rows,'weighted','current',h) for h in (7,14,30)}}
            details[phase]={mode:{key:{m:{str(h):cash_metrics([r for r in rows if r[mode]==key],m,h) for h in (7,14,30)}
                for m in models} for key in sorted({r[mode] for r in rows})} for mode in ('company','cutoff')}
        keys=('inflow_mae_rub','outflow_mae_rub','inflow_rmse_rub','outflow_rmse_rub',
              'inflow_total_mae_rub','outflow_total_mae_rub','inflow_total_rmse_rub','outflow_total_rmse_rub')
        report['preliminary_transfer']=bool(selection['eligible'] and all(p['scores']['weighted'][str(h)][k]<=p['scores']['current'][str(h)][k]*1.05
            for phase,p in report['phases'].items() if phase!='validation' for h in (7,14,30) for k in keys))
        report['sources_sha256']=self.sources
        write_json(self.output/'results.json',report);write_json(self.output/'by-company-and-period.json',details)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json')})
        print('Weighted reconciliation complete; preliminary_transfer='+str(report['preliminary_transfer']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('data/raw/weighted-reconciliation-v27'))
    args=parser.parse_args();WeightedStudy(args.output).run()
