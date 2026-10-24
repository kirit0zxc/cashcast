"""Реальные снимки: проверка дополнительного риска и полного переносимого CLI."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from .full_chronos import PHASES
from .rolling_runtime import RiskAddon
from evaluation.fallback_model.data import Dataset
from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import TxnDTO,Direction


class RiskVerifier:
    def __init__(self):
        self.addon=Path('../../outputs/cashcast-risk-addon-v21').resolve()
        self.base=Path('../../outputs/cashcast-local-candidate-v18').resolve()
        self.tabular=Path('../cashcast-eval-env/Scripts/python.exe').resolve()
        self.chronos=Path('../cashcast-chronos-env/Scripts/python.exe').resolve()
        self.out=Path('data/raw/rolling-peer-risk-v21/runtime');self.out.mkdir(exist_ok=True)
        self.data=Dataset(Path('../../outputs/cashcast-datasets-2026-10-24/01-organizers/cashflow_dataset_participants.zip'))
        self.report={'passed':False,'classifier_cases':0,'full_cli':[],'future_foreign_check':False,'db_used':False}

    def save(self):
        self.report['addon_manifest_sha256']=hashlib.sha256((self.addon/'manifest.json').read_bytes()).hexdigest()
        (self.out/'verification.json').write_text(json.dumps(self.report,indent=2),encoding='utf-8')

    def invoke(self,snapshot):
        with tempfile.TemporaryDirectory(prefix='cashcast-verify21-') as tmp:
            p=Path(tmp);inp=p/'input.json';out=p/'output.json'
            inp.write_text(json.dumps(ForecastInputCodec.encode(snapshot)),encoding='utf-8')
            result=subprocess.run([str(self.tabular),str(self.addon/'predict.py'),'--snapshot',str(inp),
                '--manifest',str(self.addon/'manifest.json'),'--base-manifest',str(self.base/'manifest.json'),
                '--tabular-python',str(self.tabular),'--chronos-python',str(self.chronos),'--output',str(out)],
                cwd=self.addon,capture_output=True,text=True,encoding='utf-8',timeout=350)
            if result.returncode:
                # Только исключение/диагностика кода, не содержимое снимка.
                raise RuntimeError(result.stderr[-3000:])
            return json.loads(out.read_text('utf-8'))

    def run(self):
        m,root=RiskAddon.manifest(self.addon/'manifest.json',self.base/'manifest.json');chosen=[]
        for phase,args in PHASES.items():
            windows,_=self.data.windows(*args);snapshots={(s.account_id,str(s.as_of)):s for s,_,_ in windows}
            rows=json.loads(Path(f'data/raw/rolling-peer-risk-v21/{phase}-rows.json').read_text('utf-8'))
            for r in rows:
                snapshot=snapshots[(r['company'],r['cutoff'])]
                stub={'candidate':'cashcast-research-18','status':'research_only','as_of':r['cutoff'],
                      'risk':{'new_gap_warning':r['risk18'],'probability_any_negative':None}}
                actual=RiskAddon.apply(stub,ForecastInputCodec.encode(snapshot),m,root)
                score=actual['risk_extension']['uncalibrated_score']
                np.testing.assert_allclose(score,r['scores']['rolling_all'],rtol=0,atol=1e-12)
                assert actual['risk']['new_gap_warning']==bool(r['risk18'] or r['scores']['rolling_all']>=.025)
                self.report['classifier_cases']+=1
            if phase=='bridge':
                r=next(r for r in rows if r['label'] and not r['risk18'] and r['scores']['rolling_all']>=.025)
            else:r=next(r for r in rows if r['label'])
            chosen.append((phase,r,snapshots[(r['company'],r['cutoff'])]))
            self.save();print(f'Classifier runtime verified {phase}: {len(rows)} cases',flush=True)
        for phase,r,snapshot in chosen:
            actual=self.invoke(snapshot)
            np.testing.assert_allclose(actual['risk_extension']['uncalibrated_score'],r['scores']['rolling_all'],atol=1e-12,rtol=0)
            assert actual['risk18']['new_gap_warning']==r['risk18']
            assert actual['risk']['new_gap_warning']==bool(r['risk18'] or r['scores']['rolling_all']>=.025)
            assert actual['risk']['probability_any_negative'] is None
            self.report['full_cli'].append({'phase':phase,'company':r['company'],'cutoff':r['cutoff'],
                                          'risk18':r['risk18'],'risk21':actual['risk']['new_gap_warning']})
            self.save();print(f'Full CLI verified {phase}',flush=True)
            if phase=='bridge':
                polluted=replace(snapshot,txns=snapshot.txns+[
                    TxnDTO('future21',snapshot.account_id,snapshot.as_of+timedelta(days=1),10**10,Direction.OUT),
                    TxnDTO('foreign21','foreign',snapshot.as_of,10**10,Direction.OUT)])
                extra=self.invoke(polluted)
                for field in ('balance_minor','risk','risk18','risk_extension'):
                    assert actual[field]==extra[field],field
                self.report['future_foreign_check']=True
                unsupported=self.invoke(replace(snapshot,horizon_days=7))
                assert unsupported['status']=='unavailable' and unsupported['risk_extension']['status']=='unavailable'
                self.report['unsupported_horizon_explicit']=True
        self.report['passed']=True;self.save();print('Runtime21 verification complete',flush=True)


if __name__=='__main__':RiskVerifier().run()
