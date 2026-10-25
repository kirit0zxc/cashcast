"""Сверка858реальных выходов25 и полного CLI по всем фазам."""
import argparse
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import numpy as np

from .crossfit_runtime import CrossfitAddon
from .full_chronos import PHASES
from .verify_rolling_runtime import RiskVerifier
from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import TxnDTO, Direction


class CrossfitVerifier(RiskVerifier):
    def run(self):
        manifest,root=CrossfitAddon.manifest(self.addon/'manifest.json',self.base/'manifest.json')
        predictions=json.loads(Path('data/raw/company-crossfit-v25/predictions.json').read_text('utf-8'))
        chosen=[]
        for phase,args in PHASES.items():
            windows,_=self.data.windows(*args)
            snapshots={(s.account_id,str(s.as_of)):s for s,_,_ in windows}
            rows=[r for r in predictions if r['phase']==phase]
            for row in rows:
                snapshot=snapshots[(row['company'],row['cutoff'])]
                stub={'candidate':'cashcast-research-18','status':'research_only','as_of':row['cutoff'],
                      'risk':{'new_gap_warning':row['risk18'],'probability_any_negative':None}}
                actual=CrossfitAddon.apply(stub,ForecastInputCodec.encode(snapshot),manifest,root)
                np.testing.assert_allclose(actual['risk_extension']['uncalibrated_score'],row['crossfit_score'],atol=1e-12,rtol=0)
                assert actual['risk_extension']['prediction_mode']==row['prediction_mode']
                assert actual['risk']['new_gap_warning']==bool(row['risk18'] or row['crossfit_score']>=.025)
                assert actual['risk']['probability_any_negative'] is None
                self.report['classifier_cases']+=1
            row=next(r for r in rows if r['label'] and (phase!='bridge' or not r['risk18']))
            chosen.append((phase,row,snapshots[(row['company'],row['cutoff'])]))
            self.save();print(f'Crossfit runtime verified {phase}: {len(rows)} cases',flush=True)
        for phase,row,snapshot in chosen:
            actual=self.invoke(snapshot)
            np.testing.assert_allclose(actual['risk_extension']['uncalibrated_score'],row['crossfit_score'],atol=1e-12,rtol=0)
            assert actual['risk18']['new_gap_warning']==row['risk18']
            assert actual['risk']['new_gap_warning']==bool(row['risk18'] or row['crossfit_score']>=.025)
            assert actual['risk']['probability_any_negative'] is None
            self.report['full_cli'].append({'phase':phase,'company':row['company'],'cutoff':row['cutoff'],
                'risk18':row['risk18'],'risk25':actual['risk']['new_gap_warning']})
            self.save();print('Full CLI25 verified '+phase,flush=True)
            if phase=='bridge':
                polluted=replace(snapshot,txns=snapshot.txns+[
                    TxnDTO('future25',snapshot.account_id,snapshot.as_of+timedelta(days=1),10**10,Direction.OUT),
                    TxnDTO('foreign25','foreign',snapshot.as_of,10**10,Direction.OUT)])
                other=self.invoke(polluted)
                for field in ('current','balance_minor','risk','risk18','risk_extension','reconciled_scenario'):
                    assert actual[field]==other[field],field
                self.report['future_foreign_check']=True
                unavailable=self.invoke(replace(snapshot,horizon_days=7))
                assert unavailable['status']=='unavailable' and unavailable['risk_extension']['status']=='unavailable'
                self.report['unsupported_horizon_explicit']=True
        self.report['passed']=True;self.save();print('Runtime25 verification complete',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('zip','addon','base','tabular-python','chronos-python'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/raw/b-runtime25'))
    args=parser.parse_args()
    CrossfitVerifier(args.zip,args.addon,args.base,args.tabular_python,args.chronos_python,args.output).run()
