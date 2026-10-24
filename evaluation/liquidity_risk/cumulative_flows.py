"""Прогноз накопленных сумм вместо суммы независимых дневных медиан."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from .flow_finetune import FlowTrainingSegments
from .finetune import FineTune
from .flow_evaluate import FlowPolicy,FlowEvaluation


class CumulativeMath:
    @staticmethod
    def context(flows,scale):
        values=np.asarray(flows,dtype=np.float64)
        if values.ndim!=2 or values.shape[0]!=2 or values.shape[1]==0 or not np.isfinite(values).all() or np.any(values<0) or not np.isfinite(scale) or scale<=0:
            raise ValueError('Нужны два конечных неотрицательных ряда')
        return np.cumsum(values*scale/1_000_000,axis=1).astype(np.float32)

    @staticmethod
    def project(predicted,last,opening):
        values=np.asarray(predicted,dtype=np.float64);last=np.asarray(last,dtype=np.float64)
        if values.shape!=(2,30,3) or last.shape!=(2,) or not np.isfinite(values).all() or not np.isfinite(last).all():
            raise ValueError('Неверная форма накопленного прогноза')
        if np.max(abs(values))*1_000_000>9e15:raise ValueError('Недопустимый масштаб')
        # Проекция фиксирована до оценки: будущая накопленная сумма не убывает.
        medians=np.sort(values,axis=2)[:,:,1]-last[:,None]
        totals=np.rint(np.maximum.accumulate(np.maximum(medians,0),axis=1)*1_000_000).astype(np.int64)
        flows=np.diff(totals,axis=1,prepend=np.zeros((2,1),dtype=np.int64)).T
        return np.column_stack([flows,opening+totals[0]-totals[1]])


class CumulativeSegments(FlowTrainingSegments):
    @classmethod
    def build(cls,dataset):
        inputs,records=super().build(dataset)
        cumulative=[CumulativeMath.context(x,1_000_000) for x in inputs]
        for record,values in zip(records,cumulative,strict=True):
            record['channels']=['cumulative_inflow','cumulative_outflow']
            record['sha256']=hashlib.sha256(values.tobytes()).hexdigest()
        return cumulative,records


class CumulativeFineTune(FineTune):
    SEGMENTS=CumulativeSegments


class CumulativePolicy(FlowPolicy):
    NAMES=('current','cum_zero','cum_ft100','cum_ft300','cum_mixzero','cum_mix100','cum_mix300')


class CumulativeEvaluation(FlowEvaluation):
    POLICY=CumulativePolicy
    RISK_POLICY='21'

    def __init__(self,training,cache,output):
        super().__init__(training,cache,output)
        sources=[Path(__file__),Path(__file__).with_name('flow_evaluate.py'),training/'training-data.json']
        sources.extend(cache/f'{kind}-{phase}.pickle' for phase in self.PHASES for kind in ('prepared','inferred'))
        FineTune.write(output/'sources.json',{'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                                           'policy':'cumulative-flow-24','independent_control':False})

    def infer(self,phases):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4);torch.manual_seed(20261025)
        source=json.loads((self.training/'training-started.json').read_text('utf-8'))['model']['snapshot']
        result={p:self.read_pickle(self.cache/f'inferred-{p}.pickle')['rows'] for p in phases}
        for name,folder in [('cum_zero',Path(source)),('cum_ft100',self.training/'checkpoint-100'),('cum_ft300',self.training/'checkpoint-300')]:
            pipeline=Chronos2Pipeline.from_pretrained(str(folder),device_map='cpu',local_files_only=True)
            for phase,rows in result.items():
                prepared=self.read_pickle(self.cache/f'prepared-{phase}.pickle')['rows']
                if [(r['company'],r['cutoff']) for r in rows]!=[(r['company'],r['cutoff']) for r in prepared]:raise ValueError('Несовпадение окон')
                indexes=[i for i,r in enumerate(prepared) if not r['fallback']]
                inputs=[CumulativeMath.context(*prepared[i]['contexts']['flow365']) for i in indexes]
                predictions,_=pipeline.predict_quantiles(inputs,prediction_length=30,quantile_levels=[.1,.5,.9],
                                    context_length=365,batch_size=16,cross_learning=False)
                for i,context,tensor in zip(indexes,inputs,predictions,strict=True):
                    rows[i]['models'][name]=CumulativeMath.project(tensor.detach().cpu().numpy(),context[:,-1],rows[i]['opening'])
                for r in rows:
                    if r['fallback']:r['models'][name]=r['models']['current'].copy()
                print(f'Cumulative inference {name} {phase}',flush=True)
            del pipeline;gc.collect()
        for phase,rows in result.items():
            for r in rows:
                for suffix,name in [('zero','cum_zero'),('100','cum_ft100'),('300','cum_ft300')]:
                    flows=np.rint(.5*r['models']['current'][:,:2]+.5*r['models'][name][:,:2]).astype(np.int64)
                    r['models'][f'cum_mix{suffix}']=np.column_stack([flows,r['opening']+np.cumsum(flows[:,0]-flows[:,1])])
            with (self.output/f'inferred-{phase}.pickle').open('wb') as f:pickle.dump(rows,f)
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('train','evaluate'));p.add_argument('--zip',type=Path)
    p.add_argument('--output',type=Path,default=Path('data/raw/cumulative-flows-v24'))
    a=p.parse_args()
    if a.stage=='train':
        if a.zip is None:p.error('--zip обязателен')
        CumulativeFineTune.train(a.zip,Path('journal/chronos-source.json'),a.output)
    else:CumulativeEvaluation(a.output,Path('data/raw/chronos-specialists-v8'),a.output/'evaluation').run()
