"""Явный список отчётов и переносимых пакетов; исходные операции не упаковываются."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def evidence():
    mappings = {
        '24': ('b-research-audit24', ('report.json', 'by-company-and-period.json')),
        '25': ('company-crossfit-v25', ('results.json', 'selection-frozen.json', 'training-audit.json', 'started.json', 'completed.json')),
        '26': ('chronos-residual-v26', ('results.json', 'by-company-and-period.json', 'selection-frozen.json', 'started.json', 'completed.json')),
        '27': ('weighted-reconciliation-v27', ('results.json', 'by-company-and-period.json', 'selection-frozen.json', 'started.json', 'completed.json')),
        '28': ('crossfit-robustness-v28', ('results.json', 'configuration-frozen.json', 'completed.json')),
        'runtime18': ('b-runtime18', ('verification.json', 'edge-verification.json')),
        'runtime21': ('b-runtime21-bytecode-off', ('verification.json',)),
        'runtime25': ('b-runtime25', ('verification.json',)),
        'runtime25-unpacked': ('b-runtime25-unpacked', ('verification.json',)),
    }
    destination = ROOT/'research_handoff/results'
    index = {}
    for label, (folder, names) in mappings.items():
        for name in names:
            source = ROOT/'data/raw'/folder/name
            data = source.read_bytes()
            json.loads(data)
            target = destination/label/name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == 'by-company-and-period.json':
                target = target.with_suffix('.json.gz')
                target.write_bytes(gzip.compress(data, mtime=0))
            else:
                target.write_bytes(data)
            index[target.relative_to(destination).as_posix()] = {
                'source': source.relative_to(ROOT).as_posix(), 'source_sha256': sha(source),
                'published_sha256': sha(target), 'source_bytes': len(data),
            }
    write(destination/'index.json', index)
    # Только имена, размеры и SHA: прогнозы/веса остаются локальными файлами.
    files = {}
    for folder in ('cumulative-flows-v24/evaluation', 'company-crossfit-v25',
                   'chronos-residual-v26', 'weighted-reconciliation-v27', 'crossfit-robustness-v28'):
        for path in sorted((ROOT/'data/raw'/folder).rglob('*')):
            if path.is_file() and path.suffix in ('.json', '.pickle', '.txt', '.cbm'):
                files[path.relative_to(ROOT).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    write(destination/'local-artifact-index.json', files)
    shutil.copyfile(ROOT/'data/raw/b-logs/final-tests.log', destination/'unit-tests.txt')
    shutil.copyfile(ROOT/'data/raw/b-logs/final-chronos-tests.log', destination/'chronos-tests.txt')
    print(f'Copied {len(index)} reports, indexed {len(files)} local artifacts')


def bundle(commit, output, addons=(25,)):
    commit = subprocess.check_output(['git', 'rev-parse', commit+'^{commit}'], cwd=ROOT, text=True).strip()
    output.mkdir(parents=True, exist_ok=False)
    assets = json.loads((ROOT/'research_handoff/assets.json').read_text('utf-8'))
    for name in ('cashcast-local-candidate-v18.zip', 'cashcast-risk-addon-v21.zip'):
        source = ROOT/'data/raw/handoff-downloads'/name
        assert sha(source) == assets[name]['sha256'], name
        shutil.copyfile(source, output/name)
    sources={25:'company-crossfit-v25',29:'diverse-risk-v29',31:'long-history-risk-v31'}
    for number in addons:
        addon = ROOT/f'data/raw/b-packages/cashcast-risk-addon-v{number}'
        manifest = json.loads((addon/'manifest.json').read_text('utf-8'))
        with zipfile.ZipFile(output/f'cashcast-risk-addon-v{number}.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
            for name in sorted([*manifest['files_sha256'], 'manifest.json']):
                path = addon/name
                if name != 'manifest.json':
                    assert sha(path) == manifest['files_sha256'][name], name
                archive.write(path, f'cashcast-risk-addon-v{number}/'+name)
        shutil.copyfile(ROOT/'data/raw'/sources[number]/'predictions.json',output/f'predictions{number}.json')
    subprocess.run(['git', 'archive', '--format=zip', '--output='+str(output/'source.zip'), commit], cwd=ROOT, check=True)
    # Только сохранённые риск-прогнозы, без банковских операций/признаков.
    documents=('B-REPRODUCE.md','B-MORNING-REPORT.md') if tuple(addons)==(25,) else ('B-CONTINUED-REPRODUCE.md','B-CONTINUED-REPORT.md')
    for name in documents:
        # Документ должен принадлежать тому же commit, что и source.zip.
        data=subprocess.check_output(['git','show',commit+':research_handoff/'+name],cwd=ROOT)
        (output/name).write_bytes(data)
    files = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()}
    write(output/'bundle-manifest.json', {'source_commit': commit,
        'source_tree': subprocess.check_output(['git', 'rev-parse', commit+'^{tree}'], cwd=ROOT, text=True).strip(),
        'files': files, 'production_activated': False, 'independent_control': False,
        'recommended_retained': ['18', '21'], 'research_addons':list(addons),
        'research_addons_status':'preliminary_only'})
    for path in output.glob('*.zip'):
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None, path.name
    target = output.with_suffix('.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_STORED) as archive:
        for path in sorted(output.iterdir()):
            archive.write(path, output.name+'/'+path.name)
    write(output.with_suffix('.receipt.json'), {'archive': str(target), 'sha256': sha(target),
        'bytes': target.stat().st_size, 'source_commit': commit, 'all_inner_zip_crc_checked': True})
    print(f'Bundle complete: {target}; SHA256 {sha(target)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('evidence', 'bundle'))
    parser.add_argument('--commit')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--addons',type=int,nargs='+',choices=(25,29,31),default=[25])
    args = parser.parse_args()
    if args.action == 'evidence':
        evidence()
    else:
        if not args.commit or not args.output:
            parser.error('bundle требует --commit и --output')
        bundle(args.commit, args.output.resolve(),tuple(args.addons))
