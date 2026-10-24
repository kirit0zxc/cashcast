"""Абляция уровня баланса и причинные месячные признаки денежного потока."""
import argparse
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np

from .distribution_run import DistributionExperiment
from .distribution import HORIZONS
from .full_chronos import PHASES
from app.modules.forecasting.v2.quality import assess_quality,validate_input


class CalendarFeatures:
    @staticmethod
    def make(snapshot,scale):
        data=validate_input(snapshot)
        quality=assess_quality(data,lookback_days=365)
        days=max(1,quality.history_days)
        start=data.as_of-timedelta(days=days-1)
        amounts=np.zeros((days,2))
        for txn in data.txns:
            if start<=txn.booked_on<=data.as_of:
                amounts[(txn.booked_on-start).days,0 if txn.direction=='in' else 1]+=txn.amount_minor/scale
        dates=[start+timedelta(days=i) for i in range(days)]
        day_of_month=np.array([d.day for d in dates])
        extra=[days]
        for direction in (0,1):
            values=amounts[:,direction]
            extra.extend([float(np.mean(values>0)),float(np.quantile(values,.9)),float(np.mean(values)),float(np.std(values))])
            means={d:float(values[day_of_month==d].mean()) if np.any(day_of_month==d) else float(values.mean()) for d in range(1,32)}
            medians={d:float(np.median(values[day_of_month==d])) if np.any(day_of_month==d) else float(np.median(values)) for d in range(1,32)}
            for horizon in HORIZONS:
                future=[(data.as_of+timedelta(days=i)).day for i in range(1,horizon+1)]
                extra.extend([sum(means[d] for d in future),sum(medians[d] for d in future)])
        months=defaultdict(float)
        for day,amount in zip(dates,amounts,strict=True):
            months[(day.year,day.month)]+=amount[0]-amount[1]
        extra.extend([float(np.mean(list(months.values()))),max(months.values()),min(months.values())])
        return np.asarray(extra)


class FlowExperiment(DistributionExperiment):
    def __init__(self,source,reference,output,variant):
        super().__init__(source,reference,output)
        self.variant=variant
        self.report['feature_variant']=variant

    def make(self,snapshot,truth):
        row=super().make(snapshot,truth)
        row['features']=np.delete(row['features'][:-2],2)
        if self.variant=='calendar':
            row['features']=np.r_[row['features'],CalendarFeatures.make(snapshot,row['scale'])]
        return row


class CalendarStudy:
    @staticmethod
    def run(source,reference,output):
        output.mkdir(parents=True,exist_ok=True)
        runners,early,comparisons={},{},{}
        for variant in ('flow_only','calendar'):
            runner=FlowExperiment(source,reference,output/variant,variant)
            runner.train();runners[variant]=runner
            validation=runner.prepare('validation')[0]
            early[variant]={'validation':validation,'bridge':runner.prepare('bridge')[0]}
            for model in runner.models:
                comparisons[f'{variant}/{model}']={str(h):runner.statistics(validation,model,h) for h in HORIZONS}
        selected=min(comparisons,key=lambda n:np.mean([comparisons[n][str(h)]['log_loss'] for h in HORIZONS]))
        variant,model=selected.split('/')
        runner=runners[variant]
        policy=runner.choose_policy(early[variant]['validation']+early[variant]['bridge'],model)
        report={'model_selection':{'selected':selected,'validation':comparisons,'source':'January-March only'},
                'policy_selection':policy,'production_activated':False,'independent_control':False,
                'calibrated':False,'release_allowed':False,'phases':{}}
        def save(name,data):
            (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        save('selection-frozen.json',{'model':report['model_selection'],'policy':policy})
        print(f'Frozen calendar selection: {selected}',flush=True)
        for phase in PHASES:
            phase_scores={}
            for candidate_variant,candidate_runner in runners.items():
                rows=early[candidate_variant].get(phase)
                if rows is None: rows=candidate_runner.prepare(phase)[0]
                for name in candidate_runner.models:
                    phase_scores[f'{candidate_variant}/{name}']={str(h):candidate_runner.statistics(rows,name,h) for h in HORIZONS}
                if candidate_variant==variant:
                    p=policy['selected']
                    selected_stats=candidate_runner.policy_stats(rows,p['model'],p['threshold'],p['mode'])
                    current=candidate_runner.statistics(rows,'current')
            report['phases'][phase]={'candidates':phase_scores,'selected_policy':selected_stats,'current_30':current}
            save('results.json',report)
            print(f'Evaluated calendar {phase}',flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();CalendarStudy.run(args.zip,args.reference,args.output)


if __name__=='__main__':main()
