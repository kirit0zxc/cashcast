"""Сборка переносимой папки: код, веса, отчёты; без выписок и окружений."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]


class CandidatePackage:
    @staticmethod
    def create(output,variant='16'):
        if variant not in ('16','18'):raise ValueError('Неизвестный вариант пакета')
        output.mkdir(parents=True,exist_ok=False)
        source=json.loads((ROOT/'journal/chronos-source.json').read_text(encoding='utf-8'))
        models={'direct':'models/direct.cbm','reserve':'models/reserve.cbm',
                'original':'models/original','finetuned':'models/finetuned'}
        sources={models['direct']:ROOT/'data/raw/fallback-model-v1/direct_depth6.cbm',
                 models['reserve']:ROOT/('data/raw/reserve-distribution-v9/cdf6.cbm' if variant=='16' else 'data/raw/forecast-reserve-v18/forecast6.cbm')}
        for name,folder in (('original',Path(source['snapshot'])),('finetuned',ROOT/'data/raw/chronos-finetune-v13/checkpoint-100')):
            for file in ('config.json','model.safetensors'):
                sources[f'{models[name]}/{file}']=folder/file
        for folder in ('evaluation','backend/app'):
            for path in (ROOT/folder).rglob('*.py'):
                sources[path.relative_to(ROOT).as_posix()]=path
        for path in (ROOT/'journal').glob('*.md'):
            sources[f'reports/{path.name}']=path
        sources['reports/ENVIRONMENTS.json']=ROOT/'journal/ENVIRONMENTS.json'
        sources['README.md']=ROOT/f'journal/{variant}-README.md'
        sources['example-input.json']=ROOT/'data/raw/chronos-finetune-v13/synthetic-snapshot.json'
        for name in ('verification.json','edge-verification.json'):
            verification=ROOT/f'data/raw/offline-candidate-v16/{name}'
            if verification.exists(): sources[f'reports/16-{name}']=verification
        for experiment,folder in (('12','horizon-ensemble-v12'),('13','chronos-finetune-v13/evaluation'),
                                  ('14','complementary-risk-v14'),('15','recall-first-v15')):
            for file in ('selection-frozen.json','results.json'):
                sources[f'reports/{experiment}-{file}']=ROOT/f'data/raw/{folder}/{file}'
        if variant=='18':
            for file in ('results.json','selection-frozen.json','verification.json'):
                sources[f'reports/18-{file}']=ROOT/f'data/raw/forecast-reserve-v18/{file}'
            for file in ('verification.json','edge-verification.json'):
                check=ROOT/f'data/raw/offline-candidate-v18/{file}'
                if check.exists():sources[f'reports/18-runtime-{file}']=check
        hashes={}
        for name,path in sources.items():
            target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
            with target.open('rb') as stream: hashes[name]=hashlib.file_digest(stream,'sha256').hexdigest()
        manifest={'schema_version':1,'policy':f'cashcast-research-{variant}','models':models,
                  'current_model':'seasonal-estimated-2.1-w84','files_sha256':hashes,
                  'training_end':'2025-12-31','original_chronos_revision':source['revision'],
                  'independent_control':False,'production_activated':False,'probability_calibrated':False}
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Package created: {len(hashes)} files; no raw dataset',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--variant',choices=('16','18'),default='16')
    args=parser.parse_args();CandidatePackage.create(args.output.resolve(),args.variant)
