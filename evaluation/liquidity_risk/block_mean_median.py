"""Фиксированная смесь денежной MAE- и MSE-модели сумм блоков."""
import argparse
from collections import Counter
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from .block_flows import BlockMath,BlockStudy
from .full_chronos import PHASES
from .research_audit import cash_metrics,cluster_intervals,deltas,digest,write_json


def money_mse_weights(rows):
    counts=Counter(r['company'] for r in rows)
    weights=np.asarray([(r['scale']*(end-start))**2/counts[r['company']]
                        for r in rows for start,end in BlockMath.BLOCKS],dtype=float)
    if not np.isfinite(weights).all() or np.any(weights<=0):raise ValueError('Неверные MSE-веса')
    return weights/weights.mean()


class MeanMedian:
    def __init__(self,median,mean):self.median,self.mean=median,mean

    def predict(self,x,**kwargs):
        return .5*(self.median.predict(x,**kwargs)+self.mean.predict(x,**kwargs))


class MeanStudy(BlockStudy):
    PARAMS={**BlockStudy.PARAMS,'loss_function':'RMSE'}

    def __init__(self,source,output):
        super().__init__(source,output)
        self.sources.update(code=digest(Path(__file__)),protocol=digest(Path('journal/35_block_mean_median.md')),
                            base_block_code=digest(Path('evaluation/liquidity_risk/block_flows.py')))

    def train(self):
        from catboost import CatBoostRegressor
        path=Path('data/raw/forecast-reserve-v18/features-train.pickle')
        original=Path('data/raw/block-flows-v30')
        source30=json.loads((original/'results.json').read_text('utf-8'))['sources_sha256']
        if digest(path)!=source30['training_cache']:raise ValueError('Изменились признаки30')
        with path.open('rb') as stream:rows=pickle.load(stream)
        x,y,_=BlockMath.training(rows);weights=money_mse_weights(rows);self.models=[]
        self.sources['training_cache']=digest(path)
        write_json(self.output/'started.json',{'params':self.PARAMS,'fixed_mean_weight':.5,'sources_sha256':self.sources,
            'windows':len(rows),'rows_per_model':len(y),'companies':len({r['company'] for r in rows}),
            'heldout_excluded':True,'max_confirmation':str(max(date.fromisoformat(r['cutoff'])+timedelta(days=37) for r in rows)),
            'sample_weights_sha256':hashlib.sha256(weights.tobytes()).hexdigest()})
        for channel in range(2):
            oldpath=original/f'block-{channel}.cbm'
            if digest(oldpath)!=source30[f'weights_{channel}']:raise ValueError('Изменились весаMAE30')
            median=CatBoostRegressor();median.load_model(str(oldpath))
            mean=CatBoostRegressor(**self.PARAMS);mean.fit(x,y[:,channel],sample_weight=weights)
            target=self.output/f'block-mean-{channel}.cbm';mean.save_model(str(target))
            loaded=CatBoostRegressor();loaded.load_model(str(target))
            np.testing.assert_allclose(mean.predict(x[:30]),loaded.predict(x[:30]),atol=1e-12,rtol=0)
            self.models.append(MeanMedian(median,loaded));self.sources[f'mean_weights_{channel}']=digest(target)
            self.sources[f'median_weights_{channel}']=digest(oldpath)
            print(f'Mean35 trained channel{channel}',flush=True)

    def run(self):
        self.train();early=self.infer('validation');selection=BlockMath.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        write_json(self.output/'selection-lock.json',{'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Frozen35: '+str(selection['selected']),flush=True)
        phases={'validation':early}
        for phase in PHASES:
            if phase!='validation':phases[phase]=self.infer(phase)
        models=('current','benchmark75_25','candidate18','candidate30',*(f'block{a}' for a in BlockMath.ALPHAS),'selected35')
        report={'selection':selection,'fixed_mean_weight':.5,'independent_control':False,'production_activated':False,
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
                row['models']['selected35']=row['models'][selection['selected']['model']].copy()
            self.sources['reference30_'+phase]=digest(oldpath)
            with (self.output/f'inferred-{phase}.pickle').open('wb') as stream:pickle.dump(rows,stream)
            report['phases'][phase]={'scores':{m:{str(h):cash_metrics(rows,m,h) for h in (7,14,30)} for m in models},
                'deltas':{base:{str(h):deltas(cash_metrics(rows,'selected35',h),cash_metrics(rows,base,h)) for h in (7,14,30)}
                          for base in ('current','benchmark75_25','candidate18','candidate30')},
                'cluster_intervals':{str(h):cluster_intervals(rows,'selected35','current',h) for h in (7,14,30)}}
            details[phase]={mode:{key:{m:{str(h):cash_metrics([r for r in rows if r[mode]==key],m,h) for h in (7,14,30)}
                for m in models} for key in sorted({r[mode] for r in rows})} for mode in ('company','cutoff')}
        keys=tuple(set(BlockMath.OBJECTIVE+BlockMath.GUARDS))
        report['preliminary_transfer']=bool(selection['selected']['alpha'] is not None and all(
            p['scores']['selected35'][str(h)][k]<=p['scores']['current'][str(h)][k]*1.05
            for phase,p in report['phases'].items() if phase!='validation' for h in (7,14,30) for k in keys))
        write_json(self.output/'results.json',report);write_json(self.output/'by-company-and-period.json',details)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json')})
        print('Mean35 complete; preliminary_transfer='+str(report['preliminary_transfer']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/raw/block-mean-median-v35'))
    args=parser.parse_args();MeanStudy(args.zip,args.output).run()
