"""Плавные веса для точечного остатка; поздние цели не участвуют в выборе."""
import argparse
import itertools
import json
import pickle
from pathlib import Path

import numpy as np

from evaluation.fallback_model.metrics import Score
from .full_chronos import PHASES


class HorizonWeights:
    @staticmethod
    def weights(current,knots):
        if current not in (0.,.25,.5) or len(knots)!=3 or any(not 0<=v<=1 for v in knots):
            raise ValueError('Неверная спецификация весов')
        chrono=np.interp(np.arange(1,31),[7,14,30],knots)
        return np.column_stack([np.full(30,current),(1-current)*(1-chrono),(1-current)*chrono])

    @classmethod
    def predict(cls,base,current,knots):
        base=np.asarray(base)
        if base.ndim!=3 or base.shape[1:]!=(30,3) or not np.isfinite(base).all():
            raise ValueError('Нужны конечные прогнозы current/direct/Chronos на30дней')
        return np.rint(np.sum(base*cls.weights(current,knots)[None,:,:],axis=2)).astype(np.int64)


class HorizonStudy:
    def __init__(self,reference,output):
        self.reference=reference;self.output=output;output.mkdir(parents=True,exist_ok=True)

    def load(self,phase):
        with (self.reference/f'inferred-{phase}.pickle').open('rb') as stream: return pickle.load(stream)['rows']

    def write(self,name,value):
        (self.output/name).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')

    @staticmethod
    def inputs(rows):
        return np.array([np.column_stack([r['models'][n][:,2] for n in ('current','direct','balance365')]) for r in rows])

    @staticmethod
    def attach(rows,predicted):
        result=[]
        for row,p in zip(rows,predicted,strict=True):
            model=row['models']['current'].copy();model[:,2]=p
            result.append({**row,'models':{**row['models'],'horizon':model}})
        return result

    def select(self,rows):
        inputs=self.inputs(rows)
        truth=np.array([r['truth'][:,2] for r in rows])
        baseline=np.array([r['models']['blend75'][:,2] for r in rows])
        months=np.array([r['cutoff'] for r in rows]);unique=np.unique(months)
        base_error=(baseline-truth)/100.
        records=[]
        for current,knots in itertools.product((0.,.25,.5),itertools.product((0.,.25,.5,.75,1.),repeat=3)):
            prediction=HorizonWeights.predict(inputs,current,knots)
            error=(prediction-truth)/100.
            ratios,month_ratios=[],[];passed=True
            for h in (7,14,30):
                mae=float(np.mean(abs(error[:,:h])));base_mae=float(np.mean(abs(base_error[:,:h])))
                rmse=float(np.sqrt(np.mean(error[:,:h]**2)));base_rmse=float(np.sqrt(np.mean(base_error[:,:h]**2)))
                passed &= mae<=base_mae*1.02+1e-9 and rmse<=base_rmse*1.02+1e-9
                ratios.append(mae/max(base_mae,.01))
                month_ratios.extend(float(np.mean(abs(error[months==m,:h])))/max(float(np.mean(abs(base_error[months==m,:h]))),.01) for m in unique)
            records.append({'current_weight':current,'chrono_knots':list(knots),'eligible':bool(passed),
                            'objective':float(np.mean(ratios)+.1*max(month_ratios)),
                            'mae_ratios':ratios,'worst_month_ratio':max(month_ratios)})
        allowed=[r for r in records if r['eligible']]
        selected=min(allowed,key=lambda r:(r['objective'],r['current_weight'],r['chrono_knots']))
        return {'selected':selected,'trials':records,'selection':'development January-March only'}

    def run(self):
        decision=self.select(self.load('validation'));self.write('selection-frozen.json',decision)
        choice=decision['selected']
        report={'selection':decision,'production_activated':False,'independent_control':False,'phases':{}}
        for phase in PHASES:
            rows=self.load(phase)
            predictions=HorizonWeights.predict(self.inputs(rows),choice['current_weight'],choice['chrono_knots'])
            rows=self.attach(rows,predictions)
            scores={}
            for name in ('current','blend75','horizon'):
                scores[name]={}
                for h in (7,14,30):
                    value=Score.summarize(rows,name,h)
                    if name!='current':value.pop('inflow_mae_rub');value.pop('outflow_mae_rub')
                    scores[name][str(h)]=value
            relative=[{**r,'models':{**r['models'],'current':r['models']['blend75']}} for r in rows]
            report['phases'][phase]={'scores':scores,'paired_vs_75_25':Score.paired_interval(relative,'horizon')}
            self.write('results.json',report)
        self.write('weights.json',{'model':'horizon-ensemble-research','experts':['current','direct_depth6','chronos365'],
                                  'day_weights':HorizonWeights.weights(choice['current_weight'],choice['chrono_knots']).tolist(),
                                  'probability':None,'production_activated':False})
        print(json.dumps(choice))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    HorizonStudy(args.reference,args.output).run()


if __name__=='__main__':main()
