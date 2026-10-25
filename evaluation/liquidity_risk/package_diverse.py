"""Явная упаковка модели29 с неизменными весами25 и без операций/pyc."""
import argparse
import json
from pathlib import Path
import shutil
from .research_audit import digest,write_json


def create(output,base,peer,training,reference):
    result=json.loads((training/'results.json').read_text('utf-8'))
    completed=json.loads((training/'completed.json').read_text('utf-8'))
    if (not result['preliminary_improvement'] or result['selection']['selected']['mode']!='mean50'
            or result['selection']['selected']['threshold']!=.05 or completed['results_sha256']!=digest(training/'results.json')
            or completed['selection_sha256']!=digest(training/'selection-frozen.json')):
        raise ValueError('Нет закреплённого результата29')
    output.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).resolve().parents[2];mapping={}
    for name in ('features.py','organizers.py'):mapping['peer/'+name]=peer/'peer'/name
    for name in ('__init__.py','rolling_runtime.py','crossfit_runtime.py','diverse_runtime.py'):
        mapping['evaluation/liquidity_risk/'+name]=source/'evaluation/liquidity_risk'/name
    for name in ('results.json','selection-frozen.json','training-audit.json','started.json','completed.json'):
        mapping['reports/'+name]=training/name
    mapping['reports/reference25-training-audit.json']=reference/'training-audit.json'
    mapping['reports/protocol.md']=source/'journal/29_diverse_risk.md'
    mapping['README.md']=source/'journal/29-README.md'
    models={};cat_models={}
    for folder,suffix,target in ((reference,'.txt',models),(training,'.cbm',cat_models)):
        audit=json.loads((folder/'training-audit.json').read_text('utf-8'))
        for path in sorted(folder.glob('*-exclude0'+suffix)):
            cutoff=path.name.removesuffix('-exclude0'+suffix);target[cutoff]=[]
            for group in range(5):
                name=f'{cutoff}-exclude{group}{suffix}'
                if digest(folder/name)!=audit[f'{cutoff}/{group}']['weights_sha256']:raise ValueError('Изменились веса')
                mapping['models/'+name]=folder/name;target[cutoff].append('models/'+name)
    if len(models)!=8 or set(models)!=set(cat_models):raise ValueError('Неполные срезы')
    for name,path in mapping.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    (output/'predict.py').write_text('from evaluation.liquidity_risk.diverse_runtime import main\n\nif __name__ == "__main__":\n    main()\n',encoding='utf-8')
    write_json(output/'manifest.json',{'policy':'cashcast-research-29','threshold':.05,'cat_weight':.5,
        'split':'sha256_byte0_mod5_holdout_byte1_mod5_group','models':models,'cat_models':cat_models,
        'base_manifest_sha256':digest(base/'manifest.json'),
        'files_sha256':{p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()},
        'probability_calibrated':False,'independent_control':False,'production_activated':False,'preliminary_only':True})
    print('Packaged29:80models, no bank operations',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('data/raw/b-packages/cashcast-risk-addon-v29'))
    parser.add_argument('--base',type=Path,default=Path('data/raw/handoff-packages/cashcast-local-candidate-v18'))
    parser.add_argument('--peer',type=Path,default=Path('data/raw/handoff-packages/cashcast-risk-addon-v21'))
    parser.add_argument('--training',type=Path,default=Path('data/raw/diverse-risk-v29'))
    parser.add_argument('--reference',type=Path,default=Path('data/raw/company-crossfit-v25'))
    args=parser.parse_args();create(args.output,args.base,args.peer,args.training,args.reference)
