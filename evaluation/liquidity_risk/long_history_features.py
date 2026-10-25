"""Переносимая копия преобразования31; совпадение проверяется на всех окнах."""
from datetime import timedelta
import numpy as np


class LongHistoryFeatures:
    WINDOWS = (28,84,180,365)

    @classmethod
    def make(cls, company, cutoff, transactions):
        from app.modules.contracts import Direction
        past = [t for t in transactions if t.account_id==company and t.booked_on<=cutoff]
        if not past: raise ValueError('Нет прошлого компании')
        start = max(min(t.booked_on for t in past), cutoff-timedelta(days=364))
        daily = np.zeros(((cutoff-start).days+1,2),dtype=float)
        for txn in past:
            if txn.booked_on>=start:
                daily[(txn.booked_on-start).days,0 if txn.direction==Direction.IN else 1] += txn.amount_minor
        scale = max(10000.,*daily[-84:].mean(axis=0))
        output = []
        for window in cls.WINDOWS:
            values=daily[-window:]/scale;net=values[:,0]-values[:,1]
            path=np.r_[0.,np.cumsum(net)]
            drawdown=float(np.max(np.maximum.accumulate(path)-path))
            features=[len(values)/window,*values.mean(axis=0),*values.std(axis=0),
                      *(values>0).mean(axis=0),float((net<0).mean()),drawdown]
            for horizon in (7,30):
                width=min(horizon,len(net));sums=np.convolve(net,np.ones(width),mode='valid')
                features.extend([float(sums.min()),float(np.quantile(sums,.1))])
            output.extend(features)
        output=np.asarray(output,dtype=float)
        if output.shape!=(52,) or not np.isfinite(output).all():raise ValueError('Неверные признаки длинной истории')
        return output

