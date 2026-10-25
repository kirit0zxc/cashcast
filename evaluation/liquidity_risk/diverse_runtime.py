"""Дополнение29: фиксированная смесь причинных CatBoost и LightGBM."""
import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np

from .crossfit_runtime import CrossfitAddon


class DiverseAddon(CrossfitAddon):
    @staticmethod
    def manifest(path,base):
        root=path.parent.resolve();manifest=json.loads(path.read_text('utf-8'))
        if (manifest.get('policy')!='cashcast-research-29' or manifest.get('threshold')!=.05 or manifest.get('cat_weight')!=.5
                or manifest.get('split')!='sha256_byte0_mod5_holdout_byte1_mod5_group'):
            raise ValueError('Неизвестная политика29')
        if hashlib.sha256(base.read_bytes()).hexdigest()!=manifest['base_manifest_sha256']:
            raise ValueError('Нужен закреплённый базовый пакет18')
        if not manifest['models'] or set(manifest['models'])!=set(manifest['cat_models']):
            raise ValueError('Несогласованные даты двух моделей')
        required=['peer/features.py','peer/organizers.py','predict.py']
        for mapping in ('models','cat_models'):
            for cutoff,models in manifest[mapping].items():
                date.fromisoformat(cutoff)
                if len(models)!=5:raise ValueError('Неполный набор групп')
                required.extend(models)
        if any(name not in manifest['files_sha256'] for name in required):raise ValueError('Незакреплённые файлы')
        for name,expected in manifest['files_sha256'].items():
            target=(root/name).resolve()
            if not target.is_relative_to(root):raise ValueError('Файл вне дополнения')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:raise ValueError('Повреждено дополнение29')
        return manifest,root

    @classmethod
    def apply(cls,base_result,snapshot,manifest,root):
        result=deepcopy(base_result)
        if result.get('candidate')!='cashcast-research-18':raise ValueError('Неверная базовая модель')
        if result['status']=='unavailable' or result.get('risk',{}).get('new_gap_warning') is None:
            result['risk_extension']={'status':'unavailable','reason':'base_risk_unavailable'}
            return result
        as_of=date.fromisoformat(snapshot['input']['as_of'])
        if result['as_of']!=str(as_of):raise ValueError('Не совпала дата baseline')
        cutoff=cls.select_model(manifest['models'],as_of)
        if cutoff is None:
            result['risk_extension']={'status':'unavailable','reason':'no_causal_checkpoint'}
            return result
        data,x=cls.features(snapshot,root)
        if data.horizon_days!=30 or data.planned_events or data.recurrences or data.scenario:
            raise ValueError('Неподдержанный вход29')
        import lightgbm as lgb
        from catboost import CatBoostClassifier
        groups=cls.groups(data.account_id);cat=[];light=[]
        for group in groups:
            light.append(float(lgb.Booster(model_file=str(root/manifest['models'][cutoff][group])).predict(x,num_threads=4)[0]))
            model=CatBoostClassifier();model.load_model(str(root/manifest['cat_models'][cutoff][group]))
            cat.append(float(model.predict_proba(x,thread_count=4)[0,1]))
        cat_score=float(np.mean(cat));light_score=float(np.mean(light));score=.5*(cat_score+light_score)
        if not np.isfinite([cat_score,light_score,score]).all() or not 0<=score<=1:raise ValueError('Неверный score29')
        result['risk18']=deepcopy(base_result['risk']);result['candidate']='cashcast-research-29'
        result['risk'].update(new_gap_warning=bool(base_result['risk']['new_gap_warning'] or score>=.05),
                              rule='risk18 OR mean50(CatBoost,LightGBM25)>=0.05',probability_any_negative=None)
        result['risk_extension']={'status':'research_only','uncalibrated_score':score,'cat_score':cat_score,
            'lightgbm25_score':light_score,'threshold':.05,'training_cutoff':cutoff,
            'staleness_days':(as_of-date.fromisoformat(cutoff)).days,
            'prediction_mode':'heldout_mean5' if len(groups)==5 else 'excluded_company_group',
            'probability_calibrated':False}
        return result


def main():
    parser=argparse.ArgumentParser()
    for name in ('snapshot','manifest','base-manifest','tabular-python','chronos-python','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=DiverseAddon.run(args.snapshot,args.manifest,args.base_manifest,args.tabular_python.resolve(),args.chronos_python.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('Исследовательское дополнение29 рассчитано; production не изменён.')


if __name__=='__main__':main()
