"""Подтверждение только дополнительных предупреждений текущим прогнозатором."""
import hashlib
import json
from pathlib import Path

from evaluation.fallback_model.data import Dataset
from .peer_specialists import PeerPolicy
from .full_chronos import PHASES


class ConfirmExtra:
    GATES=(0.,.05,.1,.25,.5)

    @staticmethod
    def flags(rows,gate):
        if gate not in ConfirmExtra.GATES:raise ValueError('Неизвестный порог подтверждения')
        return [r['risk18'] or (r['scores']['rolling_all']>=.025 and r['current']>=gate) for r in rows]

    @classmethod
    def choose(cls,rows):
        if not rows or any(r['cutoff']>'2026-06-30' or Dataset.heldout(r['company']) for r in rows):
            raise ValueError('Подбор допустим только на ранних development-строках')
        trials=[]
        for gate in cls.GATES:
            eligible=True
            for month in sorted({r['cutoff'] for r in rows}):
                sub=[r for r in rows if r['cutoff']==month]
                old=PeerPolicy.confusion(sub,cls.flags(sub,0.));new=PeerPolicy.confusion(sub,cls.flags(sub,gate))
                eligible &= new['tp']>=old['tp'] and new['fp']<=old['fp']
            trials.append({'gate':gate,'eligible':bool(eligible),'metrics':PeerPolicy.confusion(rows,cls.flags(rows,gate))})
        return {'selected':min([t for t in trials if t['eligible']],key=lambda t:(-t['metrics']['tp'],t['metrics']['fp'],t['gate'])),'trials':trials}

    @classmethod
    def run(cls):
        source=Path('data/raw/rolling-peer-risk-v21');out=Path('data/raw/confirm-extra-v22');out.mkdir(exist_ok=True)
        rows={};hashes={}
        for phase in PHASES:
            p=source/f'{phase}-rows.json';hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
            rows[phase]=json.loads(p.read_text('utf-8'))
        early=rows['validation']+rows['bridge'];selection=cls.choose(early)
        (out/'selection-frozen.json').write_text(json.dumps(selection,indent=2),encoding='utf-8')
        gate=selection['selected']['gate'];report={'selection':selection,'phases':{},'sources_sha256':hashes,
            'production_activated':False,'independent_control':False,'probability_calibrated':False}
        for phase,rs in rows.items():
            report['phases'][phase]={
                'current':PeerPolicy.confusion(rs,[r['current']>=.5 for r in rs]),
                'candidate18':PeerPolicy.confusion(rs,[r['risk18'] for r in rs]),
                'candidate21':PeerPolicy.confusion(rs,cls.flags(rs,0.)),
                'candidate22':PeerPolicy.confusion(rs,cls.flags(rs,gate))}
        report['leave_month_out']={m:cls.choose([r for r in early if r['cutoff']!=m])['selected'] for m in sorted({r['cutoff'] for r in early})}
        (out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':ConfirmExtra.run()
