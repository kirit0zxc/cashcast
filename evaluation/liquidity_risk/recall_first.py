"""Более чувствительный порог с двумя подтверждениями и помесячной защитой."""
import argparse
import json
from pathlib import Path

from .complementary import ComplementaryRisk, FusionStudy


class RecallPolicy:
    @staticmethod
    def statistics(rows,rule,threshold,current_threshold):
        adjusted=[dict(r,current=r['current_probability']>=current_threshold) for r in rows]
        return ComplementaryRisk.statistics(adjusted,rule,threshold)

    @classmethod
    def choose(cls,rows):
        candidates=[('current',.5,.5),('veto_union',.3,.5)]
        candidates += [(rule,t,c) for rule in ComplementaryRisk.RULES[1:]
                       for t in ComplementaryRisk.THRESHOLDS for c in (.05,.1,.2,.3,.4,.5)]
        months=sorted({r['cutoff'] for r in rows})
        baseline=cls.statistics(rows,'current',.5,.5)
        monthly={m:cls.statistics([r for r in rows if r['cutoff']==m],'current',.5,.5) for m in months}
        trials=[]
        for index,(rule,t,c) in enumerate(candidates):
            stats=cls.statistics(rows,rule,t,c)
            eligible=baseline['positives']>=5 and stats['tp']>=baseline['tp'] and stats['fp']<=baseline['fp']
            for month,base in monthly.items():
                subset=cls.statistics([r for r in rows if r['cutoff']==month],rule,t,c)
                eligible=eligible and subset['tp']>=base['tp'] and subset['fp']<=base['fp']
            trials.append({'rule':rule,'threshold':t,'current_threshold':c,'statistics':stats,'eligible':eligible,'order':index})
        allowed=[r for r in trials if r['eligible']]
        chosen=min(allowed,key=lambda r:(-r['statistics']['tp'],r['statistics']['fp'],
                   0 if r['order']==0 else 1 if r['order']==1 else 2,
                   ComplementaryRisk.RULES.index(r['rule']),-r['current_threshold'],r['threshold'])) if allowed else trials[0]
        return {'selected':chosen,'trials':trials,'selection':'January-June, per-month no loss versus current'}


class RecallStudy(FusionStudy):
    def load(self,phase):
        rows=super().load(phase)
        original=json.loads((self.cdf/f'{phase}-rows.json').read_text(encoding='utf-8'))
        lookup={(r['company'],r['cutoff']):r['current'] for r in original}
        for row in rows: row['current_probability']=lookup[(row['company'],row['cutoff'])]
        return rows

    def run(self):
        early={p:self.load(p) for p in self.PHASES[:2]}
        all_early=early['validation']+early['bridge']
        selection=RecallPolicy.choose(all_early)
        self.write('selection-frozen.json',selection)
        choice=selection['selected']
        print(f'Frozen recall-first: {choice}',flush=True)
        report={'selection':selection,'phases':{},'independent_control':False,'release_allowed':False,'probability_calibrated':False}
        for phase in self.PHASES:
            rows=early[phase] if phase in early else self.load(phase)
            report['phases'][phase]={
                'current':RecallPolicy.statistics(rows,'current',.5,.5),
                'candidate14':RecallPolicy.statistics(rows,'veto_union',.3,.5),
                'candidate15':RecallPolicy.statistics(rows,choice['rule'],choice['threshold'],choice['current_threshold'])}
        report['sources_sha256']=self.hashes
        self.write('results.json',report)
        print('Recall-first completed',flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cdf',type=Path,default=Path('data/raw/reserve-distribution-v9'))
    parser.add_argument('--chronos',type=Path,default=Path('data/raw/chronos-finetune-v13/evaluation'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/recall-first-v15'))
    args=parser.parse_args()
    RecallStudy(args.cdf,args.chronos,args.output).run()


if __name__=='__main__':main()
