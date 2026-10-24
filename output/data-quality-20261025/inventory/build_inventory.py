from __future__ import annotations
import hashlib, json, re, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r'C:\Users\Karp\Desktop\Hak-pos\cashcast')
DIRS = [Path(r'C:\Users\Karp\Desktop\Hak-pos\colab'), Path(r'C:\Users\Karp\Desktop\Hak-pos\model-compare-report')]
ZIPS = [Path(r'C:\Users\Karp\Downloads\Сравнение моделей CashCast.zip')]
OUT = ROOT / 'output/data-quality-20261025/inventory'
CHUNK=1024*1024

def sha_stream(stream):
    h=hashlib.sha256(); size=0
    while True:
        b=stream.read(CHUNK)
        if not b: break
        size += len(b); h.update(b)
    return size,h.hexdigest()

def sha_file(path):
    with path.open('rb') as f: return sha_stream(f)

def record_file(path, root):
    size,digest=sha_file(path)
    return {'locator': str(path.relative_to(root)).replace('\\','/'), 'kind':'file','size_bytes':size,'sha256':digest}

records=[]
for root in DIRS:
    for p in sorted(root.rglob('*')):
        if p.is_file():
            rec=record_file(p,root); rec['source_root']=str(root); records.append(rec)
for zp in ZIPS:
    if not zp.is_file():
        records.append({'locator':str(zp),'kind':'missing_archive'}); continue
    with zipfile.ZipFile(zp) as z:
        for entry_index,i in enumerate(z.infolist()):
            if i.is_dir(): continue
            with z.open(i) as f: size,digest=sha_stream(f)
            records.append({'locator':i.filename,'entry_index':entry_index,'kind':'zip_member','archive':str(zp),'size_bytes':size,'compressed_size_bytes':i.compress_size,'sha256':digest})
        archive_size,archive_sha=sha_file(zp)
        records.append({'locator':zp.name,'kind':'archive_file','source_path':str(zp),'size_bytes':archive_size,'sha256':archive_sha})
# Add zip members from the colab directory inventory, which are nested within a collected directory.
for zp in sorted(DIRS[0].rglob('*.zip')):
    try:
        with zipfile.ZipFile(zp) as z:
            for entry_index,i in enumerate(z.infolist()):
                if i.is_dir(): continue
                with z.open(i) as f: size,digest=sha_stream(f)
                records.append({'locator':i.filename,'entry_index':entry_index,'kind':'zip_member','archive':str(zp),'size_bytes':size,'compressed_size_bytes':i.compress_size,'sha256':digest})
    except (zipfile.BadZipFile, OSError) as e:
        records.append({'locator':str(zp),'kind':'archive_error','error':type(e).__name__})

# Compare report deliverable files to the downloaded report ZIP by relative member path.
report_root=DIRS[1]
report_zip=ZIPS[0]
report_comparisons=[]
if report_zip.is_file():
    with zipfile.ZipFile(report_zip) as z:
        byname={i.filename:i for i in z.infolist() if not i.is_dir()}
        for p in sorted(report_root.rglob('*')):
            if not p.is_file(): continue
            rel=p.relative_to(report_root).as_posix()
            item=byname.get(rel)
            if item is None:
                report_comparisons.append({'path':rel,'status':'missing_in_zip'}); continue
            with p.open('rb') as f: ls,lh=sha_stream(f)
            with z.open(item) as f: zs,zh=sha_stream(f)
            report_comparisons.append({'path':rel,'local_sha256':lh,'zip_sha256':zh,'status':'identical' if lh==zh else 'different','local_size':ls,'zip_size':zs})
        for name in sorted(set(byname)-{p.relative_to(report_root).as_posix() for p in report_root.rglob('*') if p.is_file()}):
            report_comparisons.append({'path':name,'status':'extra_in_zip'})

# Compare each archived evaluation/model_compare Python file to its local counterpart after CRLF normalization.
code_zip=Path(r'C:\Users\Karp\Desktop\Hak-pos\colab\cashcast-code.zip')
code_comparisons=[]
if code_zip.is_file():
    with zipfile.ZipFile(code_zip) as z:
        for name in sorted(n for n in z.namelist() if n.startswith('evaluation/model_compare/') and n.endswith('.py')):
            local=ROOT / Path(name)
            archived=z.read(name).replace(b'\r\n',b'\n')
            if not local.is_file():
                code_comparisons.append({'path':name,'status':'missing_local'}); continue
            local_bytes=local.read_bytes().replace(b'\r\n',b'\n')
            code_comparisons.append({'path':name,'status':'identical_after_crlf_normalization' if archived==local_bytes else 'different_after_crlf_normalization','archive_normalized_sha256':hashlib.sha256(archived).hexdigest(),'local_normalized_sha256':hashlib.sha256(local_bytes).hexdigest(),'archive_size':len(archived),'local_size':len(local_bytes)})

# Detect named result artifacts only from paths (never inspect transaction payloads).
artifact_records=[]
for r in records:
    path=(r.get('locator','')+' '+r.get('archive','')).lower()
    matches=[]
    if re.search(r'(^|[/\\])results?\.json($|[/\\])',path): matches.append('results_json')
    if re.search(r'prediction|per.window|window.*forecast',path): matches.append('prediction_named_path')
    if re.search(r'weight|coef|parameter',path): matches.append('weight_or_parameter_named_path')
    if matches: artifact_records.append({'locator':r.get('locator'),'kind':r.get('kind'),'archive':r.get('archive'),'matches':matches,'size_bytes':r.get('size_bytes'),'sha256':r.get('sha256')})

# Content identity groups span directory files and archive members; archive container itself is included too.
member_records=[r for r in records if r['kind']=='zip_member']
bysha=defaultdict(list)
for r in records:
    if r.get('sha256'): bysha[r['sha256']].append({'kind':r['kind'],'locator':r['locator'],'entry_index':r.get('entry_index'),'archive':r.get('archive'),'source_root':r.get('source_root')})
duplicates=[{'sha256':h,'occurrences':v} for h,v in sorted(bysha.items()) if len(v)>1]
zip_name_counts=defaultdict(int)
for r in member_records: zip_name_counts[(r['archive'],r['locator'])]+=1
duplicate_zip_names=[{'archive':a,'member_name':n,'occurrences':count} for (a,n),count in sorted(zip_name_counts.items()) if count>1]
manifest={'generated_utc':datetime.now(timezone.utc).isoformat(),'scope':{'directory_roots':[str(x) for x in DIRS],'additional_archives':[str(x) for x in ZIPS],'method':'read-only byte hashing; ZIP members streamed without extraction or execution; no transaction payloads are emitted'},'records':records,'duplicate_content_groups':duplicates,'duplicate_zip_member_names':duplicate_zip_names,'report_zip_comparisons':report_comparisons,'code_comparisons_crlf_normalized':code_comparisons,'named_result_artifact_candidates':artifact_records}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

file_records=[r for r in records if r['kind']=='file']
member_records=[r for r in records if r['kind']=='zip_member']
identical=sum(x['status']=='identical' for x in report_comparisons)
different=sum(x['status']=='different' for x in report_comparisons)
miss=sum(x['status'] in ('missing_in_zip','extra_in_zip') for x in report_comparisons)
code_ok=sum(x['status']=='identical_after_crlf_normalization' for x in code_comparisons)
code_diff=sum(x['status']!='identical_after_crlf_normalization' for x in code_comparisons)
lines=['# Полнота источников и происхождение результатов','',f"Инвентаризация создана {manifest['generated_utc']} (UTC). Проверено обычных файлов в каталогах: {len(file_records)}; ZIP-членов: {len(member_records)}; повторяющихся групп байтового содержимого: {len(duplicates)}.",'','Повтор имён членов ZIP, где обнаружен, перечислен отдельно в `manifest.json` с индексами записей, чтобы не склеивать одноимённые члены архива.','','## Поставка отчёта сравнения моделей','',f'Сопоставление `model-compare-report/` с `Сравнение моделей CashCast.zip`: одинаковы {identical}, отличаются {different}, отсутствуют с одной из сторон {miss}. Сравнение побайтовое; контрольные суммы и размеры перечислены в `manifest.json`. Графики отдельно повторно не визуально проверялись.','','## Код модели','',f'Из `cashcast-code.zip` найдено Python-файлов в `evaluation/model_compare/`: {len(code_comparisons)}. После нормализации CRLF совпали {code_ok}; отличаются или отсутствуют локально {code_diff}. Это сравнение содержимого исходников, а не подтверждение воспроизводимости вычислений.','','## Наличие результатов','', 'По именам файлов/членов архивов проверены артефакты `results.json`, предсказания по окнам и веса/параметры. Кандидаты перечислены в `manifest.json`; содержимое выписок и транзакционные строки не читались и не включались.']
if artifact_records:
    lines.append('Обнаруженные совпадения по именам:')
    for a in artifact_records: lines.append(f"- `{a['locator']}` ({', '.join(a['matches'])}, {a.get('size_bytes')} байт).")
else:
    lines.append('В перечисленных источниках нет файлов/членов с именем `results.json`, именованных предсказаний по окнам или файлов весов/параметров. Поэтому из самих поставок нельзя восстановить полный набор результатов и их веса; наличие скриншотов/графиков подтверждает только опубликованное представление, не исходные массивы.')
if code_diff:
    lines += ['', 'Файлы, отличающиеся от локальной копии: ' + ', '.join('`'+x['path']+'`' for x in code_comparisons if x['status']!='identical_after_crlf_normalization') + '.']
lines += ['', '## Дубликаты и ограничения', '', 'Полные дубликаты определены по SHA-256 идентичности всего байтового содержимого (включая вложенные члены ZIP), а не по имени. Сводка повторов находится в `manifest.json`. ZIP-файлы не извлекались и код из них не запускался. Сам манифест намеренно содержит метаданные/хеши/пути, но не содержимое транзакций.']
(OUT/'sources-completeness.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'files':len(file_records),'zip_members':len(member_records),'duplicates':len(duplicates),'report_comparisons':{'identical':identical,'different':different,'missing_or_extra':miss},'code_comparisons':{'total':len(code_comparisons),'same_after_crlf':code_ok,'different_or_missing':code_diff},'named_artifacts':len(artifact_records),'output':str(OUT)},ensure_ascii=False))
