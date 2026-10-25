"""Самостоятельный CatBoost86 и его фиксированная смесь с31."""
import argparse
import json
from pathlib import Path
import pickle

from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from .company_crossfit import CrossfitExperiment,CrossfitPolicy
from .diverse_risk import DiverseExperiment
from .research_audit import digest,reliability,write_json


class StandalonePolicy:
    THRESHOLDS=(.005,.01,.025,.05,.1,.25,.5)

    @staticmethod
    def score(row,mode):
        if mode=='cat':return row['cat_score']
        if mode=='mean50':return .5*(row['cat_score']+row['score31'])
        raise ValueError('Неизвестный режим37')

    @classmethod
    def flags(cls,rows,choice):
        return [r['risk31'] if choice['mode']=='keep31' else cls.score(r,choice['mode'])>=choice['threshold'] for r in rows]

    @classmethod
    def choose(cls,rows):
        if not rows or any(Dataset.heldout(r['company']) or r['phase'] not in CrossfitPolicy.EARLY or r['cutoff']>'2026-06-30' for r in rows):
            raise ValueError('Выбор толькораннийdevelopment')
        choices=[{'mode':'keep31','threshold':None}]+[{'mode':m,'threshold':t} for m in ('cat','mean50') for t in cls.THRESHOLDS]
        trials=[];enough=sum(r['label'] for r in rows)>=5
        for choice in choices:
            eligible=choice['mode']=='keep31' or enough
            for cutoff in sorted({r['cutoff'] for r in rows}):
                group=[r for r in rows if r['cutoff']==cutoff];labels=[r['label'] for r in group]
                old=Score.classification(labels,[r['risk31'] for r in group]);new=Score.classification(labels,cls.flags(group,choice))
                if choice['mode']!='keep31':eligible &= new['tp']>=old['tp'] and new['fp']<=old['fp']
            trials.append({**choice,'eligible':bool(eligible),'metrics':Score.classification([r['label'] for r in rows],cls.flags(rows,choice))})
        order={'keep31':0,'cat':1,'mean50':2}
        selected=min((t for t in trials if t['eligible']),key=lambda t:(-t['metrics']['tp'],t['metrics']['fp'],order[t['mode']],t['threshold'] or 0))
        return {'selected':selected,'trials':trials,'selection':'development January-June only'}


class StandaloneStudy(DiverseExperiment):
    def __init__(self,source,reference,output):
        super().__init__(source,reference,output)
        long=Path('data/raw/long-history-risk-v31')
        original=json.loads((long/'started.json').read_text('utf-8'))
        if digest(long/'prepared.pickle')!=original['prepared86_sha256']:raise ValueError('Изменились признаки31')
        with (long/'prepared.pickle').open('rb') as stream:extended=pickle.load(stream)
        lookup={(r['company'],r['as_of']):r for r in extended['train']}
        if len(lookup)!=len(self.train):raise ValueError('Изменились обучающие окна')
        for row in self.train:
            ext=lookup[(row['company'],row['as_of'])]
            if any(row[k]!=ext[k] for k in ('company','as_of','opening','label')):raise ValueError('Изменились обучающие цели')
            row['features']=ext['features']
        lookup={(r['company'],r['cutoff']):r for r in extended['control']}
        scores31={(r['company'],r['cutoff']):r for r in json.loads((long/'predictions.json').read_text('utf-8'))}
        path29=Path('data/raw/diverse-risk-v29/predictions.json')
        scores29={(r['company'],r['cutoff']):r for r in json.loads(path29.read_text('utf-8'))}
        for row in self.control:
            key=(row['company'],row['cutoff']);ext=lookup[key];a=scores31[key];b=scores29[key]
            if any(row[k]!=r[k] for r in (ext,a,b) for k in ('label','current','risk18','risk21','phase')):raise ValueError('Изменилсяbaseline')
            row['features']=ext['features'];row['score31']=a['extended_score']
            row['risk31']=bool(row['risk18'] or row['score31']>=.1)
            row['risk29']=bool(row['risk18'] or .5*(b['cat_score']+b['score25'])>=.05)
        started=json.loads((output/'started.json').read_text('utf-8'))
        started.update(code_sha256=digest(Path(__file__)),protocol_sha256=digest(Path('journal/37_standalone_long_catboost.md')),
                       prepared31_sha256=digest(long/'prepared.pickle'),predictions31_sha256=digest(long/'predictions.json'),
                       predictions29_sha256=digest(path29),diverse_helper_sha256=digest(Path('evaluation/liquidity_risk/diverse_risk.py')),
                       feature_count=86,mandatory_or18=False)
        write_json(output/'started.json',started)

    @staticmethod
    def metrics37(rows,choice):
        labels=[r['label'] for r in rows]
        flags={f'candidate{n}':[r[f'risk{n}'] for r in rows] for n in (18,21,25,29,31)}
        flags['current']=[r['current']>=.5 for r in rows];flags['selected37']=StandalonePolicy.flags(rows,choice)
        return {name:Score.classification(labels,f) for name,f in flags.items()}

    def run(self):
        early=[r for r in self.control if r['phase'] in CrossfitPolicy.EARLY]
        self.predict(early);selection=StandalonePolicy.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        write_json(self.output/'selection-lock.json',{'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Frozen37: '+str(selection['selected']),flush=True)
        self.predict([r for r in self.control if r['phase'] not in CrossfitPolicy.EARLY]);choice=selection['selected']
        report={'selection':selection,'independent_control':False,'production_activated':False,'probability_any_negative':None,
                'probability_calibrated':False,'total':self.metrics37(self.control,choice),'phases':{}}
        for phase in sorted({r['phase'] for r in self.control}):
            rows=[r for r in self.control if r['phase']==phase]
            report['phases'][phase]={'metrics':self.metrics37(rows,choice),
                'score_diagnostics':{m:reliability([r['label'] for r in rows],[StandalonePolicy.score(r,m) for r in rows]) for m in ('cat','mean50')},
                'diagnostic_fixed_policies':{m:{str(t):Score.classification([r['label'] for r in rows],StandalonePolicy.flags(rows,{'mode':m,'threshold':t}))
                    for t in StandalonePolicy.THRESHOLDS} for m in ('cat','mean50')}}
        old,new=report['total']['candidate31'],report['total']['selected37']
        preserved=all(p['metrics']['selected37']['tp']>=p['metrics']['candidate31']['tp'] for p in report['phases'].values())
        report['preliminary_dominance']=bool(preserved and new['tp']>=old['tp'] and new['fp']<old['fp'])
        report['preliminary_recall_tradeoff']=bool(preserved and new['tp']>old['tp'] and new['fp']<=report['total']['candidate25']['fp'])
        flags=StandalonePolicy.flags(self.control,choice)
        transformed=[{**r,'risk21':r['risk31'],'risk18':False,'crossfit_score':float(f)} for r,f in zip(self.control,flags,strict=True)]
        report['paired_company_bootstrap']=CrossfitExperiment.cluster_bootstrap(transformed,.5)
        report['paired_company_bootstrap']['comparison']='selected37_minus_candidate31'
        for mode in ('cutoff','company'):
            report['by_'+mode]={key:self.metrics37([r for r in self.control if r[mode]==key],choice) for key in sorted({r[mode] for r in self.control})}
        write_json(self.output/'predictions.json',[{k:v for k,v in r.items() if k!='features'} for r in self.control])
        write_json(self.output/'results.json',report)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json'),'selection_sha256':digest(self.output/'selection-frozen.json')})
        print('Standalone37 complete: '+str(report['total']['selected37']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=Path('data/raw/rolling-peer-risk-v21'))
    parser.add_argument('--reference',type=Path,default=Path('data/raw/company-crossfit-v25'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/standalone-long-risk-v37'))
    args=parser.parse_args();StandaloneStudy(args.source,args.reference,args.output).run()
