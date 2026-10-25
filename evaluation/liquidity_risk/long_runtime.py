"""Переносимое дополнение31: та же причинная схема групп, что в эксперименте."""
import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np

from .rolling_runtime import RiskAddon
from .long_history_features import LongHistoryFeatures


class LongAddon(RiskAddon):
    @staticmethod
    def manifest(path,base):
        root=path.parent.resolve();manifest=json.loads(path.read_text('utf-8'))
        if (manifest.get('policy')!='cashcast-research-31' or manifest.get('threshold')!=.1
                or manifest.get('split')!='sha256_byte0_mod5_holdout_byte1_mod5_group'):
            raise ValueError('Неизвестная политика31')
        if hashlib.sha256(base.read_bytes()).hexdigest()!=manifest['base_manifest_sha256']:
            raise ValueError('Нужен закреплённый базовый пакет18')
        required=['peer/features.py','peer/organizers.py','predict.py']
        for cutoff,models in manifest['models'].items():
            date.fromisoformat(cutoff)
            if len(models)!=5:raise ValueError('Неполный набор групповых моделей')
            required.extend(models)
        if not manifest['models'] or any(name not in manifest['files_sha256'] for name in required):
            raise ValueError('Не закреплены обязательные файлы')
        for name,digest in manifest['files_sha256'].items():
            target=(root/name).resolve()
            if not target.is_relative_to(root):raise ValueError('Файл вне дополнения')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Повреждено дополнение31')
        return manifest,root

    @staticmethod
    def features(snapshot,root):
        data,x=RiskAddon.features(snapshot,root)
        extra=LongHistoryFeatures.make(data.account_id,data.as_of,data.txns)
        return data,np.column_stack([x,extra[None,:]])

    @staticmethod
    def groups(company):
        digest=hashlib.sha256(company.encode()).digest()
        return list(range(5)) if digest[0]%5==0 else [digest[1]%5]

    @classmethod
    def apply(cls,base_result,snapshot,manifest,root):
        result=deepcopy(base_result)
        if result.get('candidate')!='cashcast-research-18':raise ValueError('Неверная базовая модель')
        if result['status']=='unavailable' or result.get('risk',{}).get('new_gap_warning') is None:
            result['risk_extension']={'status':'unavailable','reason':'base_risk_unavailable'}
            return result
        as_of=date.fromisoformat(snapshot['input']['as_of'])
        if result['as_of']!=str(as_of):raise ValueError('Не совпала дата базового результата')
        cutoff=cls.select_model(manifest['models'],as_of)
        if cutoff is None:
            result['risk_extension']={'status':'unavailable','reason':'no_causal_checkpoint'}
            return result
        data,x=cls.features(snapshot,root)
        if data.horizon_days!=30 or data.planned_events or data.recurrences or data.scenario:
            raise ValueError('Неподдержанный вход для риска31')
        import lightgbm as lgb
        groups=cls.groups(data.account_id)
        scores=[float(lgb.Booster(model_file=str(root/manifest['models'][cutoff][group])).predict(x,num_threads=4)[0]) for group in groups]
        score=float(np.mean(scores))
        if not np.isfinite(score) or not 0<=score<=1:raise ValueError('Неверный выход модели31')
        result['risk18']=deepcopy(base_result['risk'])
        result['candidate']='cashcast-research-31'
        result['risk'].update(new_gap_warning=bool(base_result['risk']['new_gap_warning'] or score>=manifest['threshold']),
                              rule='risk18 OR long_history_crossfit>=0.1',probability_any_negative=None)
        result['risk_extension']={'status':'research_only','uncalibrated_score':score,'threshold':manifest['threshold'],
            'training_cutoff':cutoff,'staleness_days':(as_of-date.fromisoformat(cutoff)).days,
            'prediction_mode':'heldout_mean5' if len(groups)==5 else 'excluded_company_group',
            'probability_calibrated':False}
        return result


def main():
    parser=argparse.ArgumentParser()
    for name in ('snapshot','manifest','base-manifest','tabular-python','chronos-python','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=LongAddon.run(args.snapshot,args.manifest,args.base_manifest,args.tabular_python.resolve(),args.chronos_python.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('Локальный исследовательский кандидат31 рассчитан; приложение не изменялось.')


if __name__=='__main__':main()
