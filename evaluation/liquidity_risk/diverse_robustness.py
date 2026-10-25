"""Три фиксированные проверки устойчивости29 без повторного выбора политики."""
import argparse
import json
from pathlib import Path

from .diverse_risk import DiverseExperiment, DiversePolicy
from .research_audit import digest, reliability, write_json


class FixedDiverse(DiverseExperiment):
    def run_fixed(self, reference):
        selection=json.loads((reference/'selection-frozen.json').read_text('utf-8'))['selected']
        if selection['mode']!='mean50' or selection['threshold']!=.05:
            raise ValueError('Изменилась исходная политика29')
        config={'params':self.PARAMS,'choice':selection,'diagnostic_only':True,'model_selection_performed':False,
                'protocol_sha256':digest(Path('journal/32_diverse_robustness.md')),'code_sha256':digest(Path(__file__)),
                'reference29_selection_sha256':digest(reference/'selection-frozen.json')}
        write_json(self.output/'configuration-frozen.json',config)
        self.predict(self.control)
        report={'configuration':config,'independent_control':False,'production_activated':False,
                'total':self.metrics29(self.control,selection),'phases':{}}
        for phase in sorted({r['phase'] for r in self.control}):
            rows=[r for r in self.control if r['phase']==phase]
            report['phases'][phase]={'metrics':self.metrics29(rows,selection),
                'raw_score_diagnostic':reliability([r['label'] for r in rows],[DiversePolicy.score(r,'mean50') for r in rows])}
        write_json(self.output/'predictions.json',[{k:v for k,v in r.items() if k!='features'} for r in self.control])
        write_json(self.output/'results.json',report)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json')})
        return report


def run(output):
    if output.exists():raise FileExistsError('Каталог уже существует; проверить живой процесс')
    output.mkdir(parents=True)
    reference=Path('data/raw/diverse-risk-v29')
    original=json.loads((reference/'results.json').read_text('utf-8'))
    variants=(('trees540',540,20261025),('trees660',660,20261025),('seed20261026',600,20261026))
    write_json(output/'configuration-frozen.json',{'variants':variants,'choice':{'mode':'mean50','threshold':.05},
        'diagnostic_only':True,'protocol_sha256':digest(Path('journal/32_diverse_robustness.md'))})
    reports={}
    for name,trees,seed in variants:
        FixedDiverse.PARAMS={**DiverseExperiment.PARAMS,'iterations':trees,'random_seed':seed}
        study=FixedDiverse(Path('data/raw/rolling-peer-risk-v21'),Path('data/raw/company-crossfit-v25'),output/name)
        reports[name]=study.run_fixed(reference)
        print(name+': '+str(reports[name]['total']['selected29']),flush=True)
    robust=all(report['total']['selected29']['fp']<original['total']['candidate25']['fp'] and all(
        p['metrics']['selected29']['tp']>=original['phases'][phase]['metrics']['selected29']['tp']
        for phase,p in report['phases'].items()) for report in reports.values())
    write_json(output/'results.json',{'diagnostic_only':True,'independent_control':False,'model_selection_performed':False,
        'all_variants_preserve_phase_tp_and_reduce_fp_vs25':bool(robust),'reference29':original['total']['selected29'],
        'variants':reports})
    write_json(output/'completed.json',{'results_sha256':digest(output/'results.json')})
    print('Robustness32 complete: '+str(robust),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('data/raw/diverse-robustness-v32'))
    args=parser.parse_args();run(args.output)
