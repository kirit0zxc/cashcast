"""Фиксированные возмущения обучения31 на неизменных86признаках."""
import argparse
import json
from pathlib import Path
import pickle

from .company_crossfit import CrossfitExperiment
from .long_history_risk import LongStudy
from .research_audit import digest,reliability,write_json


class FixedLong(LongStudy):
    def __init__(self,source,output,params):
        output.mkdir(parents=True,exist_ok=False);self.output=output;self.source=source
        started=json.loads((source/'started.json').read_text('utf-8'))
        if digest(source/'prepared.pickle')!=started['prepared86_sha256']:raise ValueError('Изменился prepared31')
        with (source/'prepared.pickle').open('rb') as stream:data=pickle.load(stream)
        self.train,self.control=data['train'],data['control'];self.models={};self.audits={};self.PARAMS=params
        write_json(output/'configuration-frozen.json',{'params':params,'threshold':.1,'mode':'extended',
            'diagnostic_only':True,'model_selection_performed':False,'prepared31_sha256':digest(source/'prepared.pickle'),
            'protocol_sha256':digest(Path('journal/33_long_robustness.md')),'code_sha256':digest(Path(__file__))})

    def run_fixed(self):
        self.predict(self.control);choice={'mode':'extended','threshold':.1}
        report={'independent_control':False,'production_activated':False,'total':self.metrics31(self.control,choice),'phases':{}}
        for phase in sorted({r['phase'] for r in self.control}):
            rows=[r for r in self.control if r['phase']==phase]
            report['phases'][phase]={'metrics':self.metrics31(rows,choice),
                'raw_score_diagnostic':reliability([r['label'] for r in rows],[r['extended_score'] for r in rows])}
        write_json(self.output/'predictions.json',[{k:v for k,v in r.items() if k!='features'} for r in self.control])
        write_json(self.output/'results.json',report)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json')})
        return report


def run(output):
    output.mkdir(parents=True,exist_ok=False);source=Path('data/raw/long-history-risk-v31')
    original=json.loads((source/'results.json').read_text('utf-8'))
    if original['selection']['selected']['mode']!='extended' or original['selection']['selected']['threshold']!=.1:
        raise ValueError('Изменилась закреплённая политика31')
    variants=(('trees270',270,42),('trees330',330,42),('seed43',300,43))
    write_json(output/'configuration-frozen.json',{'variants':variants,'threshold':.1,'model_selection_performed':False,
        'protocol_sha256':digest(Path('journal/33_long_robustness.md'))})
    reports={}
    for name,trees,seed in variants:
        params={**CrossfitExperiment.PARAMS,'n_estimators':trees,'random_state':seed}
        reports[name]=FixedLong(source,output/name,params).run_fixed()
        print(name+': '+str(reports[name]['total']['selected31']),flush=True)
    robust=all(r['total']['selected31']['fp']<original['total']['candidate25']['fp'] and all(
        p['metrics']['selected31']['tp']>=original['phases'][phase]['metrics']['selected31']['tp']
        for phase,p in r['phases'].items()) for r in reports.values())
    write_json(output/'results.json',{'diagnostic_only':True,'independent_control':False,'model_selection_performed':False,
        'all_variants_preserve_phase_tp_and_reduce_fp_vs25':bool(robust),'reference31':original['total']['selected31'],'variants':reports})
    write_json(output/'completed.json',{'results_sha256':digest(output/'results.json')})
    print('Robustness33 complete: '+str(robust),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('data/raw/long-robustness-v33'))
    args=parser.parse_args();run(args.output)
