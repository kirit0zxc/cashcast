"""Один офлайн-запуск выбранных специалистов, без вмешательства в приложение."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))

from app.core.forecast_input import ForecastInputCodec
from app.modules.forecasting.v2.quality import validate_input
from .complementary import ComplementaryRisk
from .horizon_ensemble import HorizonWeights
from .specialists import SpecialistMath


class ArtifactManifest:
    @staticmethod
    def load(path):
        manifest=json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('schema_version')!=1 or manifest.get('policy') not in ('cashcast-research-16','cashcast-research-18'):
            raise ValueError('Неподдержанная версия локального кандидата')
        root=path.parent.resolve()
        for name,digest in manifest['files_sha256'].items():
            target=(root/name).resolve()
            if not target.is_relative_to(root): raise ValueError('Артефакт вне пакета')
            with target.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=digest: raise ValueError(f'Повреждён артефакт: {name}')
        if set(manifest['models'])!={'direct','reserve','original','finetuned'}:
            raise ValueError('Неполный состав моделей')
        for value in manifest['models'].values():
            target=(root/value).resolve()
            if not target.is_relative_to(root): raise ValueError('Модель вне пакета')
            required=[target] if target.is_file() else [target/'config.json',target/'model.safetensors']
            if any(p.relative_to(root).as_posix() not in manifest['files_sha256'] for p in required):
                raise ValueError('Модель не закреплена хешем')
        return manifest,root


class CandidateWorkers:
    @staticmethod
    def tabular(snapshot,paths,forecast_reserve=False):
        from dataclasses import asdict
        from catboost import CatBoostClassifier,CatBoostRegressor
        from app.modules.forecasting.service import get_forecast_service
        from evaluation.fallback_model.features import DirectCandidate
        from .distribution import DistributionQueries
        from .model import ReserveFeatures
        data=validate_input(ForecastInputCodec.decode(snapshot))
        current=get_forecast_service().run(data)
        base=np.array([[p.inflow_minor,p.outflow_minor,p.balance_p50_minor] for p in current.points])
        result={'as_of':str(data.as_of),'opening':data.opening_balance_minor,'current':base.tolist(),
                'current_model':current.model_version,'current_risk':asdict(current.risk),'supported':True}
        if data.horizon_days!=30 or data.planned_events or data.scenario or data.recurrences:
            result.update(supported=False,reason='Кандидат исследован для30дней без явных планов/сценариев/регулярностей DTO')
            return result
        candidate=DirectCandidate(6);candidate.model=CatBoostRegressor()
        candidate.model.load_model(str(paths['direct']))
        flows,balance,_,quality=candidate.predict(data)
        result['direct']=(base if quality.history_days<28 else np.column_stack([flows,balance])).tolist()
        context=SpecialistMath.contexts(data)
        result['fallback']=context is None
        result['context']=None if context is None else context['balance365'][0].tolist()
        result['scale']=None if context is None else context['balance365'][1]
        result['reserve_score']=None
        if data.opening_balance_minor>=0 and current.risk.probability_any_negative is not None:
            features,scale,_,_=ReserveFeatures.make(data)
            if forecast_reserve:
                result['reserve_inputs']={'base_features':features.tolist(),'scale':scale,
                    'opening_minor':data.opening_balance_minor,'fallback':result['fallback'],
                    'current':current.risk.probability_any_negative,
                    'current_interval':[[p.balance_p10_minor,p.balance_p50_minor,p.balance_p90_minor] for p in current.points]}
            else:
                query=DistributionQueries.query(features,30,data.opening_balance_minor/scale)
                model=CatBoostClassifier();model.load_model(str(paths['reserve']))
                result['reserve_score']=float(model.predict_proba(query[None,:])[0,1])
        return result

    @staticmethod
    def forecast_reserve(stage,chronos,paths):
        from catboost import CatBoostClassifier
        from .forecast_features import ForecastFeatures
        from .distribution import DistributionQueries
        row=stage['reserve_inputs']
        interval=row['current_interval'] if stage['fallback'] else chronos['original']
        features=ForecastFeatures.extend(row,interval)
        query=DistributionQueries.query(features,30,row['opening_minor']/row['scale'])
        model=CatBoostClassifier();model.load_model(str(paths['reserve']))
        score=float(model.predict_proba(query[None,:])[0,1])
        if not np.isfinite(score) or not 0<=score<=1:raise ValueError('Некорректный прогнозный reserve-score')
        return {'score':score}

    @staticmethod
    def chronos(stage,paths):
        import gc
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4);torch.manual_seed(20261025)
        result={}
        if stage['fallback']: return result
        for name in ('original','finetuned'):
            model=Chronos2Pipeline.from_pretrained(str(paths[name]),device_map='cpu',local_files_only=True)
            tensors,_=model.predict_quantiles([np.array(stage['context'],dtype=np.float32)],prediction_length=30,
                    quantile_levels=[.1,.5,.9],batch_size=1,context_length=365,cross_learning=False)
            values=tensors[0].detach().cpu().numpy()[0]*stage['scale']+stage['opening']
            if values.shape!=(30,3) or not np.isfinite(values).all() or abs(values).max()>9e15:
                raise ValueError('Непригодный выход Chronos')
            result[name]=np.sort(values,axis=1).tolist()
            del model;gc.collect()
        return result


class OfflineCandidate:
    @staticmethod
    def combine(stage,chronos):
        result={'schema_version':1,'candidate':'cashcast-research-16','production_activated':False,
                'as_of':stage['as_of'],'unit':'RUB minor units','current_model':stage['current_model'],
                'current':stage['current'],'current_risk':stage['current_risk'],
                'status':'research_only' if stage['supported'] else 'unavailable',
                'limits':['Нет независимого нового контроля. Вероятности не калиброваны.',
                          'Прогнозы остатков и потоков оценены отдельно; для сверки есть отдельный сценарий.',
                          'L2-согласование потоков ухудшало их ошибки в эксперименте08.']}
        if not stage['supported']:
            result['reason']=stage['reason'];return result
        base=np.asarray(stage['current'],dtype=np.int64)
        direct=np.asarray(stage['direct'],dtype=np.int64)
        zero=base[:,2] if stage['fallback'] else np.rint(np.array(chronos['original'])[:,1]).astype(np.int64)
        tuned=base[:,2] if stage['fallback'] else np.rint(np.array(chronos['finetuned'])[:,1]).astype(np.int64)
        stacked=np.stack([base[:,2],direct[:,2],zero],axis=1)[None,:,:]
        candidate=HorizonWeights.predict(stacked,0.,(.5,1.,.75))[0]
        benchmark=np.rint(.75*zero+.25*direct[:,2]).astype(np.int64)
        result.update(fallback=stage['fallback'],balance_minor=candidate.tolist(),
                      benchmark75_25_minor=benchmark.tolist(),finetuned_balance_minor=tuned.tolist(),
                      independent_flows_minor=base[:,:2].tolist(),
                      reconciled_scenario=SpecialistMath.reconcile(base[:,:2],candidate,stage['opening']).tolist())
        probability=stage['current_risk']['probability_any_negative']
        current_flag=None if probability is None else probability>=.5
        chronos_flag=current_flag if stage['fallback'] else bool(np.any(np.array(chronos['finetuned'])[:,0]<0))
        risk={'probability_any_negative':None,'current_flag':current_flag,'chronos_p10_flag':chronos_flag,
              'reserve_uncalibrated_score':stage['reserve_score'],'rule':'current AND(Chronos OR reserve>=0.3)',
              'new_gap_warning':None,'status':'unavailable'}
        if stage['opening']<0: risk['status']='already_negative'
        elif current_flag is not None and stage['reserve_score'] is not None:
            risk.update(status='research_only',new_gap_warning=bool(ComplementaryRisk.flag(current_flag,
                         chronos_flag,stage['reserve_score']>=.3,'veto_union')))
        result['risk']=risk
        return result

    @staticmethod
    def worker(python,kind,payload):
        env=dict(os.environ,HF_HUB_OFFLINE='1',HF_HUB_DISABLE_PROGRESS_BARS='1',PYTHONIOENCODING='utf-8')
        command=[str(python),'-m','evaluation.liquidity_risk.offline_bundle','--worker',kind]
        completed=subprocess.run(command,input=json.dumps(payload),text=True,encoding='utf-8',
                                 capture_output=True,env=env,cwd=ROOT,timeout=180)
        if completed.returncode!=0:
            raise RuntimeError(f'Worker {kind} завершился с кодом {completed.returncode}; кандидат не выдан')
        return json.loads(completed.stdout)

    @classmethod
    def run(cls,snapshot,manifest_path,tabular_python,chronos_python):
        manifest,root=ArtifactManifest.load(manifest_path)
        paths={name:str(root/value) for name,value in manifest['models'].items()}
        forecast_reserve=manifest['policy']=='cashcast-research-18'
        stage=cls.worker(tabular_python,'tabular',{'snapshot':snapshot,'paths':paths,'forecast_reserve':forecast_reserve})
        if stage['current_model']!=manifest['current_model']:
            raise ValueError('Текущий движок не соответствует проверенной версии')
        chrono=cls.worker(chronos_python,'chronos',{'stage':stage,'paths':paths}) if stage['supported'] and not stage['fallback'] else {}
        if forecast_reserve and 'reserve_inputs' in stage:
            stage['reserve_score']=cls.worker(tabular_python,'reserve_forecast',{'stage':stage,'chronos':chrono,'paths':paths})['score']
        result=cls.combine(stage,chrono);result['candidate']=manifest['policy']
        return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',choices=('tabular','chronos','reserve_forecast'))
    parser.add_argument('--snapshot',type=Path)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--tabular-python',type=Path)
    parser.add_argument('--chronos-python',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.worker:
        payload=json.load(sys.stdin)
        # Библиотечный stdout не должен разрушить JSON-протокол или показать операции.
        with redirect_stdout(io.StringIO()):
            if args.worker=='tabular':result=CandidateWorkers.tabular(payload['snapshot'],payload['paths'],payload.get('forecast_reserve',False))
            elif args.worker=='chronos':result=CandidateWorkers.chronos(payload['stage'],payload['paths'])
            else:result=CandidateWorkers.forecast_reserve(payload['stage'],payload['chronos'],payload['paths'])
        print(json.dumps(result,default=str,allow_nan=False));return
    if any(v is None for v in (args.snapshot,args.manifest,args.tabular_python,args.chronos_python,args.output)):
        parser.error('Нужны snapshot,manifest,tabular-python,chronos-python,output')
    result=OfflineCandidate.run(json.loads(args.snapshot.read_text(encoding='utf-8')),args.manifest,
                                args.tabular_python.resolve(),args.chronos_python.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('Локальный кандидат рассчитан; приложение и данные не изменялись.')


if __name__=='__main__':main()
