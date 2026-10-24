"""Реальная причинность и совпадение кэшированных прогнозных признаков."""
import argparse
from dataclasses import replace
from datetime import date,timedelta
import json
from pathlib import Path
import pickle

import numpy as np

from .forecast_features import ForecastPreparation,ForecastFeatures
from .chronos_trial import BalanceContext
from .full_chronos import PHASES
from evaluation.fallback_model.data import Dataset
from app.modules.forecasting.service import get_forecast_service
from app.modules.contracts import TxnDTO,Direction


class ForecastFeatureVerification:
    @staticmethod
    def run(source,output,metadata):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4);torch.manual_seed(20261024)
        model=json.loads(metadata.read_text(encoding='utf-8'))
        pipeline=Chronos2Pipeline.from_pretrained(model['snapshot'],device_map='cpu',local_files_only=True)
        data=Dataset(source);windows,_=data.windows(*PHASES['validation'])
        lookup={(s.account_id,str(s.as_of)):(s,t) for s,t,_ in windows}
        with (output/'features-validation.pickle').open('rb') as stream:cached=pickle.load(stream)
        chosen=cached[:3];checks=[]
        for index,saved in enumerate(chosen):
            snapshot,truth=lookup[(saved['company'],saved['cutoff'])]
            current=get_forecast_service().run(snapshot)
            interval=np.array([[p.balance_p10_minor,p.balance_p50_minor,p.balance_p90_minor] for p in current.points])
            np.testing.assert_array_equal(interval,saved['current_interval'])
            context=BalanceContext.make(snapshot)
            row=ForecastPreparation.make(snapshot,truth,interval,current.risk.probability_any_negative,context)
            if context is None:quantiles=interval
            else:
                tensors,_=pipeline.predict_quantiles([context[0].astype(np.float32)[None,:]],prediction_length=30,
                    quantile_levels=[.1,.5,.9],batch_size=1,context_length=365,cross_learning=False)
                quantiles=np.sort(tensors[0].detach().cpu().numpy()[0]*context[1]+snapshot.opening_balance_minor,axis=1)
            values=ForecastFeatures.extend(row,quantiles)
            error=float(np.max(np.abs(values-saved['features'])))
            np.testing.assert_allclose(values,saved['features'],rtol=0,atol=1e-4)
            polluted=replace(snapshot,txns=snapshot.txns+[
                TxnDTO('future',snapshot.account_id,snapshot.as_of+timedelta(days=1),10**10,Direction.OUT),
                TxnDTO('other','foreign',snapshot.as_of,10**10,Direction.OUT)])
            altered=get_forecast_service().run(polluted)
            actual=np.array([[p.balance_p10_minor,p.balance_p50_minor,p.balance_p90_minor] for p in altered.points])
            np.testing.assert_array_equal(interval,actual)
            other_context=BalanceContext.make(polluted)
            if context is not None:
                np.testing.assert_array_equal(context[0],other_context[0]);assert context[1]==other_context[1]
            changed=ForecastPreparation.make(polluted,truth,actual,altered.risk.probability_any_negative,other_context)
            np.testing.assert_array_equal(values,ForecastFeatures.extend(changed,quantiles))
            checks.append({'case':index,'max_feature_error':error,'future_and_foreign_ignored':True})
        with (output/'features-train.pickle').open('rb') as stream:train=pickle.load(stream)
        assert all(date.fromisoformat(r['cutoff'])+timedelta(days=30)<=date(2025,12,31) for r in train)
        assert all(not Dataset.heldout(r['company']) for r in train)
        report={'passed':True,'cases':checks,'train_windows':len(train),'target_end':'2025-12-31',
                'heldout_companies_in_train':False,'original_chronos_revision':model['revision']}
        (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Forecast feature verification passed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/raw/forecast-reserve-v18'))
    parser.add_argument('--model-info',type=Path,default=Path('journal/chronos-source.json'))
    args=parser.parse_args();ForecastFeatureVerification.run(args.zip,args.output,args.model_info)
