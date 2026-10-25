"""Проверка переносимой папки на настоящих окнах, без запуска сервиса или БД."""
import argparse
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import pickle
import subprocess
import tempfile

import numpy as np

from .offline_bundle import ROOT
from .full_chronos import PHASES
from .horizon_ensemble import HorizonWeights
from evaluation.fallback_model.data import Dataset
from app.core.forecast_input import ForecastInputCodec


class OfflineVerifier:
    def __init__(self,source,bundle,tabular,chronos,output,reserve_source=None,reserve_model='cdf6'):
        self.dataset=Dataset(source);self.bundle=bundle;self.tabular=tabular;self.chronos=chronos;self.output=output
        output.mkdir(parents=True,exist_ok=True)
        self.report={'passed':False,'cases':[],'db_used':False,'independent_quality_evidence':False}
        self.reserve_source=reserve_source or ROOT/'data/raw/reserve-distribution-v9'
        self.reserve_model=reserve_model

    def save(self):
        (self.output/'verification.json').write_text(json.dumps(self.report,indent=2,allow_nan=False),encoding='utf-8')

    def invoke(self,snapshot):
        with tempfile.TemporaryDirectory(prefix='cashcast-offline-') as temporary:
            root=Path(temporary);input_path=root/'input.json';output_path=root/'output.json'
            input_path.write_text(json.dumps(ForecastInputCodec.encode(snapshot)),encoding='utf-8')
            result=subprocess.run([str(self.tabular),'-m','evaluation.liquidity_risk.offline_bundle',
                    '--snapshot',str(input_path),'--manifest',str(self.bundle/'manifest.json'),
                    '--tabular-python',str(self.tabular),'--chronos-python',str(self.chronos),
                    '--output',str(output_path)],cwd=self.bundle,capture_output=True,text=True,encoding='utf-8',timeout=240)
            if result.returncode: raise RuntimeError(f'Пакет не выполнил CLI: exit={result.returncode}')
            return json.loads(output_path.read_text(encoding='utf-8'))

    def run(self):
        for phase,args in PHASES.items():
            windows,_=self.dataset.windows(*args)
            snapshots={(s.account_id,str(s.as_of)):s for s,_,_ in windows}
            with (ROOT/f'data/raw/chronos-finetune-v13/evaluation/inferred-{phase}.pickle').open('rb') as stream:
                rows=pickle.load(stream)
            cdf=json.loads((self.reserve_source/f'{phase}-rows.json').read_text(encoding='utf-8'))
            reserve={(r['company'],r['cutoff']):r['scores'][self.reserve_model]['30'] for r in cdf}
            selected={i for i,r in enumerate(rows) if r['opening']>=0 and r['probability'] is not None and np.any(r['truth'][:,2]<0)}
            for condition in (lambda r:r['fallback'],lambda r:r['opening']>=0 and r['probability'] is not None and not np.any(r['truth'][:,2]<0)):
                first=next((i for i,r in enumerate(rows) if condition(r)),None)
                if first is not None:selected.add(first)
            for i in sorted(selected):
                row=rows[i];key=(row['company'],row['cutoff'])
                actual=self.invoke(snapshots[key])
                np.testing.assert_array_equal(actual['current'],row['models']['current'])
                base=np.stack([row['models'][n][:,2] for n in ('current','direct','balance365')],axis=1)[None,:,:]
                expected=HorizonWeights.predict(base,0.,(.5,1.,.75))[0]
                error=float(np.max(np.abs(np.array(actual['balance_minor'])-expected)))
                # Разная ширина torch-batch может менять последние значащие разряды.
                tolerance=max(2.,row['scale']*1e-4)
                if error>tolerance: raise AssertionError(f'Несовпадение точки: {phase}:{i} {error}>{tolerance}')
                np.testing.assert_allclose(actual['benchmark75_25_minor'],row['models']['blend75'][:,2],rtol=0,atol=tolerance)
                np.testing.assert_allclose(actual['finetuned_balance_minor'],row['models']['ft100'][:,2],rtol=0,atol=tolerance)
                if key in reserve:
                    if abs(actual['risk']['reserve_uncalibrated_score']-reserve[key])>1e-8:
                        raise AssertionError('Не совпал reserve-score')
                    current=row['probability']>=.5
                    chrono=current if row['fallback'] else bool(np.any(row['intervals']['ft100'][:,0]<0))
                    expected_flag=current and (chrono or reserve[key]>=.3)
                    if actual['risk']['new_gap_warning']!=expected_flag: raise AssertionError('Изменилось предупреждение')
                cash=np.array(actual['reconciled_scenario'])
                np.testing.assert_array_equal(row['opening']+np.cumsum(cash[:,0]-cash[:,1]),actual['balance_minor'])
                self.report['cases'].append({'phase':phase,'index':i,'positive':bool(np.any(row['truth'][:,2]<0)),
                    'fallback':row['fallback'],'max_point_difference_minor':error,'numeric_tolerance_minor':tolerance,
                    'risk_warning':actual['risk']['new_gap_warning']})
                self.save();print(f'Verified package {phase}:{i}; {len(self.report["cases"])} cases',flush=True)
        self.report['passed']=True;self.save()

    def edge_cases(self):
        from app.modules.contracts import TxnDTO,Direction
        windows,_=self.dataset.windows(*PHASES['validation'])
        snapshot=next(s for s,_,_ in windows if s.opening_balance_minor>=0)
        original=self.invoke(snapshot)
        polluted=replace(snapshot,txns=snapshot.txns+[
            TxnDTO('future-injected',snapshot.account_id,snapshot.as_of+timedelta(days=1),10**10,Direction.OUT),
            TxnDTO('foreign-injected','foreign',snapshot.as_of,10**10,Direction.OUT)])
        actual=self.invoke(polluted)
        for field in ('current','balance_minor','benchmark75_25_minor','finetuned_balance_minor','risk'):
            if actual[field]!=original[field]: raise AssertionError(f'Посторонние данные изменили {field}')
        unsupported=self.invoke(replace(snapshot,horizon_days=7))
        if unsupported['status']!='unavailable' or 'balance_minor' in unsupported or len(unsupported['current'])!=7:
            raise AssertionError('Неподдержанный горизонт выдан за проверенный кандидат')
        report={'passed':True,'future_and_foreign_ignored':True,'unsupported_horizon_explicit':True,
                'actual_model_processes':True,'db_used':False}
        (self.output/'edge-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Real package edge cases passed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--tabular-python',type=Path,required=True)
    parser.add_argument('--chronos-python',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/raw/offline-candidate-v16'))
    parser.add_argument('--edge-only',action='store_true')
    parser.add_argument('--reserve-source',type=Path)
    parser.add_argument('--reserve-model',default='cdf6')
    args=parser.parse_args()
    verifier=OfflineVerifier(args.zip,args.bundle.resolve(),args.tabular_python.resolve(),args.chronos_python.resolve(),args.output,args.reserve_source,args.reserve_model)
    verifier.edge_cases() if args.edge_only else verifier.run()
