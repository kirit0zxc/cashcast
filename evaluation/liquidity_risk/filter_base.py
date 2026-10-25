"""Обновляемый детектор как фильтр и источник дополнительных предупреждений."""
import hashlib
import json
from pathlib import Path

from .confirm_extra import ConfirmExtra
from .peer_specialists import PeerPolicy
from .full_chronos import PHASES


class FilterBase(ConfirmExtra):
    GATES=(0.,.001,.005,.01,.025)

    @staticmethod
    def flags(rows,gate):
        if gate not in FilterBase.GATES:raise ValueError('Неизвестный порог фильтра')
        return [(r['risk18'] and r['scores']['rolling_all']>=gate) or r['scores']['rolling_all']>=.025 for r in rows]

    @classmethod
    def run(cls):
        source=Path('data/raw/rolling-peer-risk-v21');out=Path('data/raw/filter-base-v23');out.mkdir(exist_ok=True)
        rows={};hashes={}
        for phase in PHASES:
            p=source/f'{phase}-rows.json';hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
            rows[phase]=json.loads(p.read_text('utf-8'))
        early=rows['validation']+rows['bridge']
        if sum(r['label'] for r in early)<5:raise ValueError('Недостаточно положительных ранних окон')
        selection=cls.choose(early)
        (out/'selection-frozen.json').write_text(json.dumps(selection,indent=2),encoding='utf-8')
        gate=selection['selected']['gate'];report={'selection':selection,'phases':{},'sources_sha256':hashes,
            'production_activated':False,'independent_control':False,'probability_calibrated':False}
        safe=True
        for phase,rs in rows.items():
            before=cls.flags(rs,0.);after=cls.flags(rs,gate)
            lost=[{'company':r['company'],'cutoff':r['cutoff']} for r,b,a in zip(rs,before,after,strict=True) if r['label'] and b and not a]
            safe &= not lost
            report['phases'][phase]={'current':PeerPolicy.confusion(rs,[r['current']>=.5 for r in rs]),
                'candidate18':PeerPolicy.confusion(rs,[r['risk18'] for r in rs]),
                'candidate21':PeerPolicy.confusion(rs,before),'candidate23':PeerPolicy.confusion(rs,after),'lost_true_alerts':lost}
        report['preserves_all_observed_true_alerts']=safe
        report['leave_month_out']={m:cls.choose([r for r in early if r['cutoff']!=m])['selected'] for m in sorted({r['cutoff'] for r in early})}
        (out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':FilterBase.run()
