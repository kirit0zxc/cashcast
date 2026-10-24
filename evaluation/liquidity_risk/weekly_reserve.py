"""Недельная история обучения; выбор резерва и политики до поздних проверок."""
import argparse
from datetime import date,timedelta
import hashlib
import json
import pickle
from pathlib import Path
import time

import numpy as np

from .distribution_run import DistributionExperiment
from .distribution import DistributionQueries,DistributionModel,HORIZONS
from .full_chronos import PHASES
from .complementary import ComplementaryRisk
from .recall_first import RecallPolicy


class WeeklyReserve(DistributionExperiment):
    NAME='weekly6'
    @staticmethod
    def dates():
        values=[];day=date(2024,12,31)
        while day+timedelta(days=30)<=date(2025,12,31):
            values.append(day);day+=timedelta(days=7)
        return values

    def train(self):
        from catboost import CatBoostClassifier
        windows,excluded=self.data.windows(self.dates(),date(2025,12,31))
        rows=[self.make(s,t) for s,t,_ in windows]
        rows=[r for r in rows if r['history_days']>=28]
        natural=[r for r in rows if r['opening']>=0]
        self.priors={str(h):(sum(np.any(r['truth'][:h,2]<0) for r in natural)+.5)/(len(natural)+1) for h in HORIZONS}
        x,y,w=DistributionQueries.augment(rows)
        self.report['train']={'windows':len(rows),'companies':len({r['company'] for r in rows}),
             'queries':len(y),'positive_windows':{str(h):sum(bool(np.any(r['truth'][:h,2]<0)) for r in natural) for h in HORIZONS},
             'positive_companies':{str(h):len({r['company'] for r in natural if np.any(r['truth'][:h,2]<0)}) for h in HORIZONS},
             'priors':self.priors,'excluded':excluded,'target_end':'2025-12-31','stride':7}
        self.write('results.json',self.report)
        print(f'Weekly training: {len(rows)} windows, {len(y)} queries',flush=True)
        started=time.perf_counter();model=DistributionModel(6).fit(x,y,w)
        model.model.save_model(str(self.output/'weekly6.cbm'));self.models['weekly6']=model
        old=DistributionModel(6);old.model=CatBoostClassifier()
        old.model.load_model(str(self.output.parent/'reserve-distribution-v9/cdf6.cbm'))
        self.models['cdf6']=old
        print(f'Weekly model trained in {time.perf_counter()-started:.1f}s',flush=True)

    def fusion_rows(self,phase,rows,model):
        serialized=[{k:r[k] for k in ('company','cutoff','opening','current')} |
                    {'scores':{'cdf6':r['scores'][model]},'labels':{'30':bool(np.any(r['truth'][:,2]<0))}} for r in rows]
        with (self.output.parent/f'chronos-finetune-v13/evaluation/inferred-{phase}.pickle').open('rb') as stream:
            forecasts=pickle.load(stream)
        joined=ComplementaryRisk.join(serialized,forecasts)
        lookup={(r['company'],r['cutoff']):r['current'] for r in rows}
        for row in joined:row['current_probability']=lookup[(row['company'],row['cutoff'])]
        return joined

    def run(self):
        self.train()
        early={p:self.prepare(p)[0] for p in ('validation','bridge')}
        scores={n:{str(h):self.statistics(early['validation'],n,h) for h in HORIZONS} for n in self.models}
        selected=min(scores,key=lambda n:(np.mean([scores[n][str(h)]['log_loss'] for h in HORIZONS]),n!='cdf6'))
        fusion=sum([self.fusion_rows(p,r,selected) for p,r in early.items()],[])
        old_fusion=sum([self.fusion_rows(p,r,'cdf6') for p,r in early.items()],[])
        policy=RecallPolicy.choose(fusion)
        old_stats=RecallPolicy.statistics(old_fusion,'veto_union',.3,.5)
        new_stats=policy['selected']['statistics']
        use_old=(-old_stats['tp'],old_stats['fp'])<=(-new_stats['tp'],new_stats['fp'])
        choice={'model':'cdf6','rule':'veto_union','threshold':.3,'current_threshold':.5} if use_old else {'model':selected,**{k:policy['selected'][k] for k in ('rule','threshold','current_threshold')}}
        self.report['selection']={'reserve_model':selected,'reserve_trials':scores,'policy_search':policy,
                                  'old14_statistics':old_stats,'selected':choice,'source':'January-June only'}
        self.write('selection-frozen.json',self.report['selection'])
        print(f'Frozen reserve selection ({self.NAME}): {choice}',flush=True)
        self.report['phases']={}
        for phase in PHASES:
            rows=early[phase] if phase in early else self.prepare(phase)[0]
            joined=self.fusion_rows(phase,rows,choice['model']);old_rows=self.fusion_rows(phase,rows,'cdf6')
            self.report['phases'][phase]={'reserve_scores':{n:{str(h):self.statistics(rows,n,h) for h in HORIZONS} for n in self.models},
                'current':RecallPolicy.statistics(joined,'current',.5,.5),
                'candidate14':RecallPolicy.statistics(old_rows,'veto_union',.3,.5),
                'selected':RecallPolicy.statistics(joined,choice['rule'],choice['threshold'],choice['current_threshold'])}
            serial=[{k:r[k] for k in ('company','cutoff','opening','current','scores')} |
                    {'labels':{str(h):bool(np.any(r['truth'][:h,2]<0)) for h in HORIZONS}} for r in rows]
            self.write(f'{phase}-rows.json',serial)
            self.write('results.json',self.report);print(f'Evaluated reserve ({self.NAME}) {phase}',flush=True)
        self.report['weights_sha256']=hashlib.sha256((self.output/f'{self.NAME}.cbm').read_bytes()).hexdigest()
        self.report['release_allowed']=False
        self.write('results.json',self.report)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--reference',type=Path,default=Path('data/raw/chronos-specialists-v8'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/weekly-reserve-v17'))
    args=parser.parse_args();WeeklyReserve(args.zip,args.reference,args.output).run()
