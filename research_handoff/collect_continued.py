"""Сохраняет только завершённые агрегаты29–37, без признаков и банковских операций."""
import argparse
import gzip
import json
from pathlib import Path
import shutil

from package_b import sha,write,ROOT


EXPERIMENTS={
    '29':'diverse-risk-v29','30':'block-flows-v30','31':'long-history-risk-v31',
    '32':'diverse-robustness-v32','33':'long-robustness-v33','34':'rolling-reserve-quantiles-v34',
    '35':'block-mean-median-v35','36':'rolling-block-flows-v36','37':'standalone-long-risk-v37',
}
NAMES=('results.json','selection-frozen.json','selection-lock.json','configuration-frozen.json',
       'started.json','completed.json','training-audit.json','by-company-and-period.json')


def collect(tests=None):
    output=ROOT/'research_handoff/results-continued';output.mkdir(parents=True,exist_ok=True)
    (output/'.gitattributes').write_text('# Сохранять исходные байты отчётов для SHA.\n* -text whitespace=cr-at-eol\n',encoding='utf-8')
    index={};artifacts={};pending=[]
    def copy_report(path,target):
        data=path.read_bytes();json.loads(data)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.name=='by-company-and-period.json':
            target=target.with_suffix('.json.gz');target.write_bytes(gzip.compress(data,mtime=0))
        else:target.write_bytes(data)
        index[target.relative_to(output).as_posix()]={'source':path.relative_to(ROOT).as_posix(),
            'source_sha256':sha(path),'published_sha256':sha(target),'source_bytes':len(data)}
    for number,folder in EXPERIMENTS.items():
        source=ROOT/'data/raw'/folder
        if not (source/'completed.json').exists():pending.append(number);continue
        completion=json.loads((source/'completed.json').read_text('utf-8'))
        if sha(source/'results.json')!=completion['results_sha256']:raise ValueError('Изменён завершённый отчёт'+number)
        for directory in (source,*sorted(p for p in source.iterdir() if p.is_dir())):
            for name in NAMES:
                path=directory/name
                if path.is_file():copy_report(path,output/number/path.relative_to(source))
        for path in source.rglob('*'):
            if path.is_file() and path.suffix in ('.json','.pickle','.txt','.cbm'):
                artifacts[path.relative_to(ROOT).as_posix()]={'bytes':path.stat().st_size,'sha256':sha(path)}
    for number in (29,31):
        source=ROOT/f'data/raw/b-runtime{number}/verification.json'
        if source.exists() and json.loads(source.read_text('utf-8')).get('passed'):
            copy_report(source,output/f'runtime{number}/verification.json')
    tests=tests or ROOT/'data/raw/b-logs/continued-tests-audit.log'
    if not tests.read_text('utf-8').rstrip().endswith('OK'):raise ValueError('Нет полного успешного тестового прогона')
    shutil.copyfile(tests,output/'unit-tests.txt')
    write(output/'index.json',index);write(output/'local-artifact-index.json',artifacts)
    write(output/'status.json',{'completed_experiments':[n for n in EXPERIMENTS if n not in pending],
        'incomplete_experiments':pending,'independent_control':False,'production_activated':False})
    print(f'Collected {len(index)} completed reports, {len(artifacts)} local artifact hashes; pending {pending}')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--tests-log',type=Path)
    args=parser.parse_args();collect(args.tests_log)
