"""Локальное сравнение заранее заданных смесей без исполнения внешнего кода."""
import csv
import hashlib
import json
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np

from evaluation.fallback_model.data import Dataset


class PeerPolicy:
    WEIGHTS = (0., .25, .5, .75, 1.)
    EARLY = ('2026-04-30', '2026-05-31', '2026-06-30')

    @staticmethod
    def mix(first, second, weight):
        if weight not in PeerPolicy.WEIGHTS:
            raise ValueError('Неизвестный вес')
        return (1-weight)*np.asarray(first)+weight*np.asarray(second)

    @staticmethod
    def metrics(rows, name, column):
        errors=np.array([r[name][:,column]-r['truth'][:,column] for r in rows])/100.
        result={}
        for h in (7,14,30):
            e=errors[:,:h]
            result[f'mae{h}']=float(np.abs(e).mean())
            result[f'rmse{h}']=float(np.sqrt(np.square(e).mean()))
            if column!=2:
                sums=e.sum(axis=1)
                result[f'total_mae{h}']=float(np.abs(sums).mean())
                result[f'total_rmse{h}']=float(np.sqrt(np.square(sums).mean()))
        return result

    @classmethod
    def choose(cls, rows, column):
        # Селектор дополнительно запрещает поздние даты и контрольные компании.
        if not rows or any(r['cutoff'] not in cls.EARLY or Dataset.heldout(r['company']) for r in rows):
            raise ValueError('Для выбора нужны только ранние development-окна')
        base_name='fixed' if column==2 else 'current'
        base=cls.metrics(rows,base_name,column)
        trials=[]
        for w in cls.WEIGHTS:
            mixed=[{**r,'candidate':cls.mix(r[base_name],r['peer'],w)} for r in rows]
            score=cls.metrics(mixed,'candidate',column)
            ratios=[score[k]/max(base[k],.01) for k in base]
            eligible=all(score[k]<=base[k]*1.05+1e-8 for k in base)
            for month in cls.EARLY:
                sub=[r for r in mixed if r['cutoff']==month]
                if not sub:continue
                old=cls.metrics(sub,base_name,column);new=cls.metrics(sub,'candidate',column)
                eligible &= all(new[k]<=old[k]*1.1+1e-8 for k in old if 'mae' in k)
            trials.append({'weight':w,'eligible':bool(eligible),'objective':float(np.mean(ratios)),
                           'metrics':score})
        choice=min((t for t in trials if t['eligible']),key=lambda t:(t['objective'],t['weight']))
        return {'selected':choice,'trials':trials}

    @staticmethod
    def risk_flags(rows, source, threshold):
        if source=='keep':return [r['risk18'] for r in rows]
        return [r['risk18'] or r[source]>=threshold for r in rows]

    @staticmethod
    def confusion(rows, flags):
        counts=dict(tp=0,fp=0,fn=0,tn=0)
        for r,p in zip(rows,flags,strict=True):
            y=r['label'];counts['tp' if y and p else 'fn' if y else 'fp' if p else 'tn']+=1
        return counts

    @classmethod
    def choose_risk(cls, rows):
        if not rows or any(r['cutoff'] not in cls.EARLY or Dataset.heldout(r['company']) for r in rows):
            raise ValueError('Поздние строки нельзя использовать для выбора риска')
        trials=[]
        for source,threshold in [('keep',.5)]+[(s,t) for s in ('peer_classifier','peer_quantile') for t in (.05,.1,.25,.5)]:
            scores=cls.confusion(rows,cls.risk_flags(rows,source,threshold));eligible=True
            for month in cls.EARLY:
                sub=[r for r in rows if r['cutoff']==month]
                s=cls.confusion(sub,cls.risk_flags(sub,source,threshold))
                current=cls.confusion(sub,[r['probability']>=.5 for r in sub])
                old=cls.confusion(sub,[r['risk18'] for r in sub])
                eligible &= s['fp']<=current['fp'] and s['tp']>=old['tp']
            trials.append({'source':source,'threshold':threshold,'metrics':scores,'eligible':bool(eligible)})
        allowed=[t for t in trials if t['eligible']]
        choice=min(allowed,key=lambda t:(-t['metrics']['tp'],t['metrics']['fp'],t['source']!='keep',t['threshold'])) if sum(r['label'] for r in rows)>=2 else trials[0]
        return {'selected':choice,'trials':trials}


class PeerStudy:
    PHASES=('validation','bridge','late_development','other_early','late_other')

    def __init__(self, output=Path('data/raw/peer-specialists-v20')):
        self.output=output;output.mkdir(parents=True,exist_ok=True);self.hashes={}

    def read(self, path, kind):
        data=path.read_bytes();self.hashes[str(path)]=hashlib.sha256(data).hexdigest()
        if kind=='pickle':return pickle.loads(data)  # Только наши доверенные кэши.
        if kind=='csv':return list(csv.DictReader(data.decode('utf-8-sig').splitlines()))
        return json.loads(data)

    def write(self, name, value):
        (self.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

    @staticmethod
    def daily(rr, original):
        if len(rr)!=30 or sorted(int(r['h']) for r in rr)!=list(range(1,31)):
            raise ValueError('Пропущены или повторены дни горизонта')
        rr=sorted(rr,key=lambda r:int(r['h']))
        truth=np.array([[float(r[f'actual_{k}_rub']) for k in ('inflow','outflow','balance')] for r in rr])*100
        current=np.array([[float(r[f'current_2_1_w84_{k}_rub']) for k in ('inflow','outflow','p50')] for r in rr])*100
        peer=np.array([[float(r[f'lightgbm_global_{k}_rub']) for k in ('inflow','outflow','p50')] for r in rr])*100
        if not np.isfinite(peer).all():raise ValueError('Неконечный прогноз')
        np.testing.assert_allclose(truth,original['truth'],rtol=0,atol=.001)
        np.testing.assert_allclose(current,original['models']['current'],rtol=0,atol=.001)
        return {**original,'current':current,'peer':peer,'fixed':original['models']['blend75']}

    def load(self):
        peer=Path('data/raw/peer-danil/export-2026-10-25/out')
        daily=defaultdict(list)
        for r in self.read(peer/'predictions_daily.csv','csv'):daily[(r['company_id'],r['as_of'])].append(r)
        risk_rows=self.read(peer/'predictions_risk.csv','csv')
        risk={(r['company_id'],r['as_of']):r for r in risk_rows}
        if len(risk)!=len(risk_rows):raise ValueError('Повтор окна риска')
        rows=[];missing=[]
        for phase in self.PHASES:
            originals=self.read(Path(f'data/raw/chronos-specialists-v8/inferred-{phase}.pickle'),'pickle')['rows']
            ft=self.read(Path(f'data/raw/chronos-finetune-v13/evaluation/inferred-{phase}.pickle'),'pickle')
            ft={(r['company'],r['cutoff']):r for r in ft}
            cdf=self.read(Path(f'data/raw/forecast-reserve-v18/{phase}-rows.json'),'json')
            cdf={(r['company'],r['cutoff']):r for r in cdf}
            for original in originals:
                key=(original['company'],original['cutoff'])
                if key not in daily:continue
                row=self.daily(daily[key],original);row['phase']=phase
                row['risk_available']=original['opening']>=0 and original['probability'] is not None
                if row['risk_available']:
                    p=risk[key];f=ft[key];c=cdf[key]
                    label=bool(np.any(row['truth'][:,2]<0))
                    if label!=bool(int(p['label_any_negative_30d'])) or abs(float(p['prob_current_2_1_w84'])-original['probability'])>1e-8:
                        raise ValueError('Риск и факт не совпадают')
                    current=original['probability']>=.5
                    chronos=current if f['fallback'] else bool(np.any(f['intervals']['ft100'][:,0]<0))
                    row.update(label=label,risk18=current and (chronos or c['scores']['forecast6']['30']>=.3),
                               peer_classifier=float(p['prob_lightgbm_classifier']),peer_quantile=float(p['prob_lightgbm_min_quantiles']))
                rows.append(row)
        covered={(r['company'],r['cutoff']) for r in rows}
        missing=sorted(set(daily)-covered)
        self.write('sources.json',{'sha256':self.hashes,'matched':len(rows),'unmatched':missing})
        return rows

    def run(self):
        rows=self.load()
        early=[r for r in rows if r['cutoff'] in PeerPolicy.EARLY and not Dataset.heldout(r['company'])]
        selection={name:PeerPolicy.choose(early,col) for name,col in [('inflow',0),('outflow',1),('balance',2)]}
        selection['risk']=PeerPolicy.choose_risk([r for r in early if r['risk_available']])
        self.write('selection-frozen.json',selection)
        for r in rows:
            r['candidate']=r['current'].copy()
            for name,col in [('inflow',0),('outflow',1),('balance',2)]:
                base=r['fixed'] if col==2 else r['current']
                r['candidate'][:,col]=PeerPolicy.mix(base[:,col],r['peer'][:,col],selection[name]['selected']['weight'])
        report={'selection':selection,'groups':{},'production_activated':False,'independent_control':False,
                'peer_companies_held_out_from_training':False,'risk_probability_calibrated':False}
        groups={'early_development':early,'early_other':[r for r in rows if r['cutoff'] in PeerPolicy.EARLY and Dataset.heldout(r['company'])],
                'late_development':[r for r in rows if r['cutoff']>'2026-06-30' and not Dataset.heldout(r['company'])],
                'late_other':[r for r in rows if r['cutoff']>'2026-06-30' and Dataset.heldout(r['company'])]}
        for name,sub in groups.items():
            risk=[r for r in sub if r['risk_available']];policy=selection['risk']['selected']
            report['groups'][name]={'windows':len(sub),'risk_windows':len(risk),
                'metrics':{n:{target:PeerPolicy.metrics(sub,n,col) for target,col in [('inflow',0),('outflow',1),('balance',2)]} for n in ('current','fixed','peer','candidate')},
                'risk':{'current':PeerPolicy.confusion(risk,[r['probability']>=.5 for r in risk]),
                        'candidate18':PeerPolicy.confusion(risk,[r['risk18'] for r in risk]),
                        'candidate20':PeerPolicy.confusion(risk,PeerPolicy.risk_flags(risk,policy['source'],policy['threshold']))}}
        self.write('results.json',report)
        print(json.dumps({k:v['selected'] for k,v in selection.items()},ensure_ascii=False))


if __name__=='__main__':PeerStudy().run()
