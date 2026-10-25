"""Переносимое преобразование31 совпадает с обучением и не видит будущее."""
from datetime import date,timedelta
from pathlib import Path
import unittest
import numpy as np
from .long_history_risk import LongHistoryFeatures as TrainingFeatures
from .long_history_features import LongHistoryFeatures as RuntimeFeatures
from .long_runtime import LongAddon
from app.modules.contracts import Direction,TxnDTO


class LongRuntimeTests(unittest.TestCase):
    def test_portable_transform_matches_training_and_ignores_future_foreign(self):
        day=date(2026,5,31)
        txns=[TxnDTO(str(i),'a',day-timedelta(days=i),10000*(i%5+1),Direction.IN if i%3 else Direction.OUT) for i in range(400)]
        expected=TrainingFeatures.make('a',day,txns)
        extras=[TxnDTO('future','a',day+timedelta(days=1),10**12,Direction.OUT),TxnDTO('foreign','b',day,10**12,Direction.OUT)]
        np.testing.assert_array_equal(expected,RuntimeFeatures.make('a',day,txns+extras))

    def test_no_causal_checkpoint_is_explicit(self):
        base={'candidate':'cashcast-research-18','status':'research_only','as_of':'2025-01-01','risk':{'new_gap_warning':False}}
        result=LongAddon.apply(base,{'input':{'as_of':'2025-01-01'}},{'models':{'2026-01-31':[]}},Path('.'))
        self.assertEqual(result['risk_extension']['reason'],'no_causal_checkpoint')
        self.assertNotIn('risk_extension',base)


if __name__=='__main__':unittest.main()
