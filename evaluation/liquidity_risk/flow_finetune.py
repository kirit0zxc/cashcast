"""Два денежных потока на сверенной истории, без искусственного заполнения пропусков."""
import argparse
from collections import defaultdict
from datetime import timedelta
import hashlib
from pathlib import Path

import numpy as np

from .finetune import TrainingSegments,FineTune
from evaluation.fallback_model.data import Dataset


class FlowTrainingSegments(TrainingSegments):
    @classmethod
    def build(cls,dataset):
        inputs,manifest=[],[]
        for company,transactions in sorted(dataset.transactions.items()):
            if Dataset.heldout(company):continue
            segments=cls.segments(company,transactions,dataset.balances[company],cls.LIMIT)
            eligible=[s for s in segments if len(s[2])-1>=86]
            if not eligible:continue
            start,end,balances=min(eligible,key=lambda s:(-len(s[2]),s[0]))
            daily=defaultdict(lambda:[0,0])
            for txn in transactions:
                if txn.account_id==company and start<txn.booked_on<=end:
                    daily[txn.booked_on][0 if txn.direction=='in' else 1]+=txn.amount_minor
            days=[start+timedelta(days=i) for i in range(1,len(balances))]
            values=np.array([daily[d] for d in days],dtype=np.int64).T
            np.testing.assert_array_equal(balances[0]+np.cumsum(values[0]-values[1]),balances[1:])
            if np.any(values<0):raise ValueError('Отрицательный поток')
            normalized=(values.astype(np.float64)/1_000_000).astype(np.float32)
            inputs.append(normalized)
            manifest.append({'company':company,'start':str(days[0]),'end':str(end),'days':len(days),
                             'anchor_eod':str(start),'channels':['inflow','outflow'],
                             'sha256':hashlib.sha256(normalized.tobytes()).hexdigest()})
        if not inputs:raise ValueError('Нет сверенных рядов потоков достаточной длины')
        return inputs,manifest


class FlowFineTune(FineTune):
    SEGMENTS=FlowTrainingSegments


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--model-info',type=Path,default=Path('journal/chronos-source.json'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/flow-finetune-v19'))
    args=parser.parse_args();FlowFineTune.train(args.zip,args.model_info,args.output)
