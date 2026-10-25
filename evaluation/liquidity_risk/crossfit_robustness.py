"""Три заранее заданных возмущения обучения; не выбирает победивший seed."""
import argparse
import json
from pathlib import Path

from .company_crossfit import CrossfitExperiment
from .research_audit import digest, reliability, write_json


class RobustnessRun(CrossfitExperiment):
    def run_fixed(self,reference):
        config={'threshold':.025,'params':self.PARAMS,'diagnostic_only':True,'model_selection_performed':False,
                'reference25_selection_sha256':digest(reference/'selection-frozen.json'),
                'protocol28_sha256':digest(Path('journal/28_crossfit_robustness.md')),
                'runner_code_sha256':digest(Path(__file__))}
        write_json(self.output/'configuration-frozen.json',config)
        # Гиперпараметры/порог неизменны; все модели соблюдают своё as_of независимо от фазы.
        self.predict(self.control)
        report={'configuration':config,'independent_control':False,'production_activated':False,'phases':{},
                'total':self.metrics(self.control,.025)}
        for phase in sorted({r['phase'] for r in self.control}):
            rows=[r for r in self.control if r['phase']==phase]
            report['phases'][phase]={'metrics':self.metrics(rows,.025),
                'raw_score_diagnostic':reliability([r['label'] for r in rows],[r['crossfit_score'] for r in rows])}
        write_json(self.output/'predictions.json',[{k:v for k,v in r.items() if k!='features'} for r in self.control])
        write_json(self.output/'results.json',report)
        write_json(self.output/'completed.json',{'results_sha256':digest(self.output/'results.json')})
        return report


def run(output):
    if output.exists():raise FileExistsError('Каталог повторов уже существует; проверить процесс')
    output.mkdir(parents=True)
    reference=Path('data/raw/company-crossfit-v25')
    original=json.loads((reference/'results.json').read_text('utf-8'))
    variants=(('trees270',270,42),('trees330',330,42),('seed43',300,43))
    write_json(output/'configuration-frozen.json',{'variants':variants,'threshold':.025,'diagnostic_only':True,
        'protocol_sha256':digest(Path('journal/28_crossfit_robustness.md'))})
    reports={}
    for name,trees,seed in variants:
        RobustnessRun.PARAMS={**CrossfitExperiment.PARAMS,'n_estimators':trees,'random_state':seed}
        study=RobustnessRun(Path('data/raw/rolling-peer-risk-v21'),output/name)
        reports[name]=study.run_fixed(reference)
        print('Robustness '+name+': '+str(reports[name]['total']['selected25']),flush=True)
    robust=all(report['total']['selected25']['fp']<original['total']['candidate21']['fp'] and all(
        phase['metrics']['selected25']['tp']>=original['phases'][name]['metrics']['selected25']['tp']
        for name,phase in report['phases'].items()) for report in reports.values())
    write_json(output/'results.json',{'diagnostic_only':True,'model_selection_performed':False,'independent_control':False,
        'reference25':original['total']['selected25'],'reference21':original['total']['candidate21'],
        'all_variants_preserve_phase_tp_and_reduce_total_fp':bool(robust),'variants':reports})
    write_json(output/'completed.json',{'results_sha256':digest(output/'results.json')})
    print('Robustness complete: '+str(robust),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('data/raw/crossfit-robustness-v28'))
    args=parser.parse_args();run(args.output)
