"""Дополнение21 к переносимому кандидату18: более чувствительный риск, те же прогнозы."""
import argparse
from copy import deepcopy
from datetime import date
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

import numpy as np


class RiskAddon:
    @staticmethod
    def manifest(path,base):
        root=path.parent.resolve();m=json.loads(path.read_text('utf-8'))
        if m.get('policy')!='cashcast-research-21' or m.get('threshold')!=.025:
            raise ValueError('Неизвестная политика риска')
        if hashlib.sha256(base.read_bytes()).hexdigest()!=m['base_manifest_sha256']:
            raise ValueError('Нужен закреплённый базовый пакет18')
        for name,digest in m['files_sha256'].items():
            target=(root/name).resolve()
            if not target.is_relative_to(root):raise ValueError('Файл вне дополнения')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Повреждено дополнение')
        for filename in [*m['models'].values(),'peer/features.py','peer/organizers.py','predict.py']:
            if filename not in m['files_sha256']:raise ValueError('Не закреплён обязательный файл')
        return m,root

    @staticmethod
    def select_model(models,as_of):
        available=sorted(k for k in models if date.fromisoformat(k)<=as_of)
        return available[-1] if available else None

    @staticmethod
    def features(snapshot,root):
        from app.core.forecast_input import ForecastInputCodec
        from app.modules.forecasting.v2.quality import validate_input
        data=validate_input(ForecastInputCodec.decode(snapshot))
        # Отдельный namespace не исполняет содержимое чужого __init__.py.
        namespace='_cashcast_risk_addon_'+hashlib.sha256(str(root).encode()).hexdigest()[:10]
        pkg=types.ModuleType(namespace);pkg.__path__=[str(root/'peer')]
        sys.modules.setdefault(namespace,pkg)
        Company=importlib.import_module(namespace+'.organizers').Company
        vector=importlib.import_module(namespace+'.features').risk_vector
        ctx=Company(data.account_id,sorted(data.txns,key=lambda t:(t.booked_on,t.id)),
                    {b.balance_date:b.closing_balance_minor for b in data.daily_balances})
        window=ctx.snapshot(data.as_of)
        if window.opening!=data.opening_balance_minor:
            raise ValueError('Стартовый остаток отличается от подтверждённой истории')
        return data,np.array(vector(window),dtype=float)[None,:]

    @classmethod
    def apply(cls,base_result,snapshot,manifest,root):
        result=deepcopy(base_result)
        if base_result.get('candidate')!='cashcast-research-18':raise ValueError('Неверная базовая модель')
        # Неподдержанный вход не превращаем в якобы готовое предупреждение.
        if result['status']=='unavailable' or result.get('risk',{}).get('new_gap_warning') is None:
            result['risk_extension']={'status':'unavailable','reason':'base_risk_unavailable'}
            return result
        as_of=date.fromisoformat(snapshot['input']['as_of'])
        if result['as_of']!=str(as_of):raise ValueError('Не совпала дата базового результата')
        selected=cls.select_model(manifest['models'],as_of)
        if selected is None:
            result['risk_extension']={'status':'unavailable','reason':'no_causal_checkpoint'};return result
        data,x=cls.features(snapshot,root)
        if data.horizon_days!=30 or data.planned_events or data.recurrences or data.scenario:
            raise ValueError('Неподдержанный вход для риска21')
        import lightgbm as lgb
        model=lgb.Booster(model_file=str(root/manifest['models'][selected]))
        score=float(model.predict(x,num_threads=4)[0])
        if not np.isfinite(score) or not 0<=score<=1:raise ValueError('Неверный выход модели')
        result['risk18']=deepcopy(base_result['risk'])
        result['candidate']='cashcast-research-21'
        result['risk'].update(new_gap_warning=bool(base_result['risk']['new_gap_warning'] or score>=manifest['threshold']),
                              rule='risk18 OR rolling_LightGBM>=0.025',probability_any_negative=None)
        result['risk_extension']={'status':'research_only','uncalibrated_score':score,'threshold':manifest['threshold'],
                                  'training_cutoff':selected,'staleness_days':(as_of-date.fromisoformat(selected)).days,
                                  'probability_calibrated':False}
        return result

    @classmethod
    def run(cls,snapshot_path,manifest_path,base_manifest,tabular,chronos):
        m,root=cls.manifest(manifest_path,base_manifest)
        base_root=base_manifest.parent.resolve()
        sys.path.insert(0,str(base_root));sys.path.insert(0,str(base_root/'backend'))
        snapshot=json.loads(snapshot_path.read_text('utf-8'))
        with tempfile.TemporaryDirectory(prefix='cashcast-risk21-') as tmp:
            output=Path(tmp)/'base.json'
            process=subprocess.run([str(tabular),'-m','evaluation.liquidity_risk.offline_bundle',
                '--snapshot',str(snapshot_path.resolve()),'--manifest',str(base_manifest.resolve()),
                '--tabular-python',str(tabular),'--chronos-python',str(chronos),'--output',str(output)],
                cwd=base_root,capture_output=True,text=True,encoding='utf-8',timeout=300)
            if process.returncode:raise RuntimeError(f'Базовый кандидат не выполнился: exit={process.returncode}')
            base=json.loads(output.read_text('utf-8'))
        return cls.apply(base,snapshot,m,root)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('snapshot','manifest','base-manifest','tabular-python','chronos-python','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    result=RiskAddon.run(a.snapshot,a.manifest,a.base_manifest,a.tabular_python.resolve(),a.chronos_python.resolve())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('Локальный кандидат21 рассчитан; приложение не изменялось.')
