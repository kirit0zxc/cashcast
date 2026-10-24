"""Проверка SHA и безопасное восстановление приватных исследовательских артефактов."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import stat
import zipfile


class Restore:
    @staticmethod
    def validate(archive,target):
        root=target.resolve();seen=set()
        for info in archive.infolist():
            name=info.filename;p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name or stat.S_ISLNK(info.external_attr>>16):
                raise ValueError('Недопустимый путь в архиве')
            key=name.casefold()
            if key in seen:raise ValueError('Повтор пути в архиве')
            seen.add(key)
            destination=(root/Path(*p.parts)).resolve()
            if not destination.is_relative_to(root):raise ValueError('Путь вышел за целевой каталог')

    @classmethod
    def extract(cls,path,target,dry_run):
        with zipfile.ZipFile(path) as archive:
            cls.validate(archive,target)
            if archive.testzip() is not None:raise ValueError('CRC архива не совпал')
            if dry_run:return
            for info in archive.infolist():
                dest=target.joinpath(*PurePosixPath(info.filename).parts)
                if info.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
                if dest.exists():raise FileExistsError(f'Файл уже существует: {dest}; используй чистый каталог')
                dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(info) as source,dest.open('xb') as output:shutil.copyfileobj(source,output)

    @staticmethod
    def copy_models(source,target):
        target.mkdir(parents=True,exist_ok=True)
        for name in ('config.json','model.safetensors'):
            dest=target/name
            # Малые config уже могли прийти в исследовательском архиве.
            if dest.exists():
                if hashlib.sha256(dest.read_bytes()).hexdigest()!=hashlib.sha256((source/name).read_bytes()).hexdigest():
                    raise ValueError('Разошлись конфигурации весов')
                continue
            try:os.link(source/name,dest)
            except OSError:shutil.copyfile(source/name,dest)

    @classmethod
    def run(cls,downloads,root,manifest,dry_run=False):
        assets=json.loads(manifest.read_text('utf-8'))
        # Сначала проверяются все файлы, до распаковки и десериализации кэшей.
        for name,entry in assets.items():
            path=downloads/name
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if digest!=entry['sha256'] or path.stat().st_size!=entry['bytes']:raise ValueError('Не совпал SHA/размер: '+name)
        for name in assets:
            if name=='cashcast-local-candidate-v18.zip':target=root/'data/raw/handoff-packages/cashcast-local-candidate-v18'
            elif name=='cashcast-risk-addon-v21.zip':target=root/'data/raw/handoff-packages/cashcast-risk-addon-v21'
            else:target=root
            # Веса в больших архивах повторяют config из малого: распаковываем только отсутствующие файлы.
            if name.startswith('cashcast-chronos-'):
                with zipfile.ZipFile(downloads/name) as z:
                    cls.validate(z,target)
                    if z.testzip() is not None:raise ValueError('Повреждён архив весов')
                    if not dry_run:
                        for info in z.infolist():
                            dest=target.joinpath(*PurePosixPath(info.filename).parts)
                            if dest.exists():
                                if hashlib.sha256(dest.read_bytes()).digest()!=hashlib.sha256(z.read(info)).digest():raise ValueError('Разошёлся повтор файла весов')
                                continue
                            dest.parent.mkdir(parents=True,exist_ok=True)
                            with z.open(info) as src,dest.open('xb') as dst:shutil.copyfileobj(src,dst)
            else:cls.extract(downloads/name,target,dry_run)
            print('Verified '+name,flush=True)
        if dry_run:return
        package=root/'data/raw/handoff-packages/cashcast-local-candidate-v18'
        original=root/'data/raw/hf-cache/models--amazon--chronos-2/snapshots/29ec3766d36d6f73f0696f85560a422f50e8498c'
        cls.copy_models(package/'models/original',original)
        cls.copy_models(package/'models/finetuned',root/'data/raw/chronos-finetune-v13/checkpoint-100')
        # Меняются только локальные абсолютные пути в метаданных; веса остаются прежними.
        for folder in ('chronos-finetune-v13','flow-finetune-v19','cumulative-flows-v24'):
            p=root/'data/raw'/folder/'training-started.json'
            value=json.loads(p.read_text('utf-8'));value['model']['snapshot']=str(original.resolve())
            p.write_text(json.dumps(value,indent=2),encoding='utf-8')
        print('Restore complete. No application/database commands were executed.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--downloads',type=Path,required=True)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--dry-run',action='store_true')
    a=p.parse_args();Restore.run(a.downloads.resolve(),a.root.resolve(),Path(__file__).with_name('assets.json'),a.dry_run)
