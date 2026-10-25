"""Упаковка дополнения25 без исходных выписок, признаков и окружений."""
import argparse
import json
from pathlib import Path
import shutil

from .research_audit import digest, write_json


def create(output,base,peer,training):
    result=json.loads((training/'results.json').read_text('utf-8'))
    completed=json.loads((training/'completed.json').read_text('utf-8'))
    audit=json.loads((training/'training-audit.json').read_text('utf-8'))
    if (not result['preliminary_improvement'] or result['selection']['selected']['threshold']!=.025
            or completed['results_sha256']!=digest(training/'results.json')):
        raise ValueError('Нет подтверждённого результата для закреплённой политики25')
    output.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).resolve().parents[2]
    mapping={}
    for name in ('features.py','organizers.py'):
        mapping['peer/'+name]=peer/'peer'/name
    for path in (source/'evaluation/liquidity_risk').glob('*.py'):
        if path.name in ('__init__.py','crossfit_runtime.py','rolling_runtime.py'):
            mapping['evaluation/liquidity_risk/'+path.name]=path
    for name in ('results.json','selection-frozen.json','training-audit.json','started.json','completed.json'):
        mapping['reports/'+name]=training/name
    mapping['reports/protocol.md']=source/'journal/25_company_crossfit.md'
    mapping['README.md']=source/'journal/25-README.md'
    models={}
    for path in sorted(training.glob('*-exclude0.txt')):
        cutoff=path.name.removesuffix('-exclude0.txt')
        models[cutoff]=[]
        for group in range(5):
            name=f'{cutoff}-exclude{group}.txt'
            if digest(training/name)!=audit[f'{cutoff}/{group}']['weights_sha256']:
                raise ValueError('Веса отличаются от обучающего аудита')
            mapping['models/'+name]=training/name
            models[cutoff].append('models/'+name)
    for name,path in mapping.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    (output/'predict.py').write_text('from evaluation.liquidity_risk.crossfit_runtime import main\n\nif __name__ == "__main__":\n    main()\n',encoding='utf-8')
    hashes={p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()}
    write_json(output/'manifest.json',{'policy':'cashcast-research-25','threshold':.025,
        'split':'sha256_byte0_mod5_holdout_byte1_mod5_group','base_manifest_sha256':digest(base/'manifest.json'),
        'models':models,'files_sha256':hashes,'probability_calibrated':False,
        'independent_control':False,'production_activated':False,'preliminary_only':True})
    print(f'Packaged candidate25 addon: {len(models)*5} models; no raw data',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('data/raw/b-packages/cashcast-risk-addon-v25'))
    parser.add_argument('--base',type=Path,default=Path('data/raw/handoff-packages/cashcast-local-candidate-v18'))
    parser.add_argument('--peer',type=Path,default=Path('data/raw/handoff-packages/cashcast-risk-addon-v21'))
    parser.add_argument('--training',type=Path,default=Path('data/raw/company-crossfit-v25'))
    args=parser.parse_args();create(args.output,args.base,args.peer,args.training)
