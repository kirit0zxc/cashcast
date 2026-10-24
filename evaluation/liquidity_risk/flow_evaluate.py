"""Отдельная оценка потоков и согласованного остатка с неизменным baseline."""
import argparse
import gc
import itertools
import json
from pathlib import Path
import pickle

import numpy as np

from .finetune import FineTune
from .finetune_evaluate import FineTuneEvaluation
from .horizon_ensemble import HorizonWeights
from evaluation.fallback_model.metrics import Score


class FlowPolicy:
    NAMES=('current','flow365','flow_ft100','flow_ft300','flow_mix100','flow_mix300')

    @staticmethod
    def assemble(row,incoming,outgoing):
        if incoming=='keep_current' or row.get('fallback',False):return np.asarray(row['models']['current']).copy()
        values=np.column_stack([row['models'][incoming][:,0],row['models'][outgoing][:,1]])
        if values.shape!=(30,2) or not np.isfinite(values).all() or np.any(values<0):
            raise ValueError('Непригодные дневные потоки')
        values=np.rint(values).astype(np.int64)
        return np.column_stack([values,row['opening']+np.cumsum(values[:,0]-values[:,1])])

    @classmethod
    def score(cls,rows,incoming,outgoing,horizon):
        views=[dict(r,models={'candidate':cls.assemble(r,incoming,outgoing)}) for r in rows]
        score=Score.summarize(views,'candidate',horizon)
        for channel,name in ((0,'inflow'),(1,'outflow')):
            errors=np.stack([(r['models']['candidate'][:horizon,channel]-r['truth'][:horizon,channel])/100 for r in views])
            score[f'{name}_rmse_rub']=float(np.sqrt(np.mean(errors**2)))
            score[f'{name}_total_mae_rub']=float(np.mean(np.abs(errors.sum(axis=1))))
        return score

    @classmethod
    def choose(cls,rows):
        base={str(h):cls.score(rows,'keep_current',None,h) for h in (7,14,30)}
        errors=('inflow_mae_rub','outflow_mae_rub','inflow_total_mae_rub','outflow_total_mae_rub','mae_rub')
        baseline_objective=float(np.mean([base[h][key]/max(base[h][key],1e-12) for h in base for key in errors]))
        choices=[{'incoming':'keep_current','outgoing':None,'objective':baseline_objective,'eligible':True,'scores':base}]
        for incoming,outgoing in itertools.product(cls.NAMES,repeat=2):
            scores={str(h):cls.score(rows,incoming,outgoing,h) for h in (7,14,30)}
            eligible=all(scores[h][key]<=base[h][key]*1.05 for h in base for key in ('rmse_rub','inflow_rmse_rub','outflow_rmse_rub'))
            objective=float(np.mean([scores[h][key]/max(base[h][key],1e-12) for h in base for key in errors]))
            choices.append({'incoming':incoming,'outgoing':outgoing,'objective':objective,'eligible':eligible,'scores':scores})
        selected=min([v for v in choices if v['eligible']],key=lambda r:(r['objective'],r['incoming']!='keep_current',r['incoming'],r['outgoing'] or ''))
        return {'selected':selected,'trials':choices,'selection':'development January-March only'}


class FlowEvaluation(FineTuneEvaluation):
    POLICY=FlowPolicy
    RISK_POLICY='18'
    def infer(self,phases):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4);torch.manual_seed(20261025)
        result={p:self.read_pickle(self.cache/f'inferred-{p}.pickle')['rows'] for p in phases}
        for name,step in (('flow_ft100',100),('flow_ft300',300)):
            pipeline=Chronos2Pipeline.from_pretrained(str(self.training/f'checkpoint-{step}'),device_map='cpu',local_files_only=True)
            for phase,rows in result.items():
                prepared=self.read_pickle(self.cache/f'prepared-{phase}.pickle')['rows']
                if [(r['company'],r['cutoff']) for r in prepared]!=[(r['company'],r['cutoff']) for r in rows]:
                    raise ValueError('Несовпадение исходных окон')
                indexes=[i for i,r in enumerate(prepared) if not r['fallback']]
                inputs=[prepared[i]['contexts']['flow365'][0].astype(np.float32) for i in indexes]
                predictions,_=pipeline.predict_quantiles(inputs,prediction_length=30,quantile_levels=[.1,.5,.9],
                                  context_length=365,batch_size=16,cross_learning=False)
                for i,tensor in zip(indexes,predictions,strict=True):
                    values=tensor.detach().cpu().numpy()*prepared[i]['contexts']['flow365'][1]
                    if values.shape!=(2,30,3) or not np.isfinite(values).all() or np.max(abs(values))>9e15:
                        raise ValueError('Непригодные прогнозы потоков')
                    values=np.sort(values,axis=2)
                    flows=np.rint(np.maximum(values[:,:,1].T,0)).astype(np.int64)
                    rows[i]['models'][name]=np.column_stack([flows,rows[i]['opening']+np.cumsum(flows[:,0]-flows[:,1])])
                for row in rows:
                    if row['fallback']:row['models'][name]=row['models']['current'].copy()
                print(f'Flow inference {name} {phase}',flush=True)
            del pipeline;gc.collect()
        for phase,rows in result.items():
            for row in rows:
                for step in (100,300):
                    flows=np.rint(.5*row['models']['current'][:,:2]+.5*row['models'][f'flow_ft{step}'][:,:2]).astype(np.int64)
                    row['models'][f'flow_mix{step}']=np.column_stack([flows,row['opening']+np.cumsum(flows[:,0]-flows[:,1])])
            with (self.output/f'inferred-{phase}.pickle').open('wb') as stream:pickle.dump(rows,stream)
        return result

    def run(self):
        early=self.infer(('validation',));policy=self.POLICY.choose(early['validation'])
        FineTune.write(self.output/'selection-frozen.json',policy)
        choice=policy['selected'];print(f'Frozen flows: {choice["incoming"]}/{choice["outgoing"]}',flush=True)
        later=self.infer(self.PHASES[1:])
        self.score(policy,{**early,**later})

    def score_saved(self):
        policy=json.loads((self.output/'selection-frozen.json').read_text(encoding='utf-8'))
        self.score(policy,{p:self.read_pickle(self.output/f'inferred-{p}.pickle') for p in self.PHASES})

    def score(self,policy,rows_by_phase):
        choice=policy['selected']
        report={'selection':policy,'phases':{},'independent_control':False,'production_activated':False,
                'risk_policy_unchanged':self.RISK_POLICY,'probability_calibrated':False,'release_allowed':False}
        for phase,rows in rows_by_phase.items():
            for row in rows:
                values=np.stack([row['models'][n][:,2] for n in ('current','direct','balance365')],axis=1)[None,:,:]
                predicted=HorizonWeights.predict(values,0.,(.5,1.,.75))[0]
                row['models']['horizon12']=np.column_stack([row['models']['current'][:,:2],predicted])
            pairs=[('current','keep_current',None),('selected',choice['incoming'],choice['outgoing'])]
            pairs += [('current_coherent' if n=='current' else n,n,n) for n in self.POLICY.NAMES]
            scores={label:{str(h):self.POLICY.score(rows,incoming,outgoing,h) for h in (7,14,30)} for label,incoming,outgoing in pairs}
            for label,name in (('benchmark75_25','blend75'),('benchmark12','horizon12')):
                scores[label]={str(h):Score.summarize(rows,name,h) for h in (7,14,30)}
                for score in scores[label].values():
                    score.pop('inflow_mae_rub');score.pop('outflow_mae_rub')
            report['phases'][phase]={'scores':scores,'fallback_windows':sum(r['fallback'] for r in rows),
                                    'fallback_preserves_native_current':True}
            FineTune.write(self.output/'results.json',report)
        report['weights_sha256']={str(step):FineTune.fingerprints(self.training/f'checkpoint-{step}') for step in (100,300)}
        FineTune.write(self.output/'results.json',report);print('Flow evaluation completed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--training',type=Path,default=Path('data/raw/flow-finetune-v19'))
    parser.add_argument('--cache',type=Path,default=Path('data/raw/chronos-specialists-v8'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/flow-finetune-v19/evaluation'))
    parser.add_argument('--score-only',action='store_true')
    args=parser.parse_args();evaluation=FlowEvaluation(args.training,args.cache,args.output)
    evaluation.score_saved() if args.score_only else evaluation.run()
