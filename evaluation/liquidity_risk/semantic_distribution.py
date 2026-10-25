"""Прошлая структура платежей без передачи идентификаторов в модель."""
import argparse
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np

from .distribution_run import DistributionExperiment
from app.modules.categorization.service import get_categorizer
from app.modules.contracts import Category
from app.modules.forecasting.v2.quality import assess_quality,validate_input


class SemanticFeatures:
    @staticmethod
    def concentration(amounts):
        known=defaultdict(float);unknown=total=0.
        for key,amount in amounts:
            total+=amount
            if key is None or not str(key).strip(): unknown+=amount
            else: known[key]+=amount
        known_total=sum(known.values())
        shares=[v/known_total for v in known.values()] if known_total else []
        return [sum(s*s for s in shares),max(shares,default=0.),unknown/total if total else 0.,float(len(known))]

    @classmethod
    def make(cls,snapshot,scale):
        data=validate_input(snapshot)
        quality=assess_quality(data,lookback_days=365)
        days=max(1,quality.history_days)
        start=data.as_of-timedelta(days=days-1)
        txns=[t for t in data.txns if start<=t.booked_on<=data.as_of]
        assigned=get_categorizer().categorize(txns)
        ages=np.array([(data.as_of-t.booked_on).days for t in txns],dtype=int)
        amounts=np.array([t.amount_minor/scale for t in txns],dtype=float)
        directions=np.array([0 if t.direction=='in' else 1 for t in txns],dtype=int)
        categories=np.array([a.category.value for a in assigned],dtype=str)
        values=[]
        for direction in (0,1):
            for category in Category:
                mask=(directions==direction)&(categories==category.value)
                for window in (28,84):
                    active=mask&(ages<window)
                    gross=float(amounts[ages<window].sum())
                    values.extend([float(amounts[active].sum())/min(window,days),
                                   float(active.sum())/min(window,days),
                                   float(amounts[active].sum())/gross if gross else 0.])
                values.append(float(ages[mask].min())/365 if np.any(mask) else 1.)
            relevant=[(t.counterparty_ref or t.counterparty_name,t.amount_minor/scale)
                      for t in txns if (0 if t.direction=='in' else 1)==direction and (data.as_of-t.booked_on).days<84]
            values.extend(cls.concentration(relevant))
            recent=float(amounts[(directions==direction)&(ages<28)].sum())/min(28,days)
            prior_days=max(1,min(84,days)-28)
            earlier=float(amounts[(directions==direction)&(ages>=28)&(ages<84)].sum())/prior_days
            values.extend([recent,earlier,recent-earlier,recent/(earlier+1.)])
        result=np.asarray(values,dtype=float)
        if not np.isfinite(result).all(): raise ValueError('Нечисловые признаки семантики')
        return result


class SemanticExperiment(DistributionExperiment):
    @staticmethod
    def make(snapshot,truth):
        row=DistributionExperiment.make(snapshot,truth)
        row['features']=np.r_[row['features'],SemanticFeatures.make(snapshot,row['scale'])]
        return row


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    SemanticExperiment(args.zip,args.reference,args.output).run(args.resume)


if __name__=='__main__':main()
