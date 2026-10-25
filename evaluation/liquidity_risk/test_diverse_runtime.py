"""Границы причинного runtime29 и запрет подмены фиксированной смеси."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from .diverse_runtime import DiverseAddon


class DiverseRuntimeTests(unittest.TestCase):
    def test_unavailable_is_explicit_and_does_not_mutate_base(self):
        base={'candidate':'cashcast-research-18','status':'unavailable','balance_minor':[123]}
        saved=deepcopy(base)
        result=DiverseAddon.apply(base,{}, {},Path('.'))
        self.assertEqual(base,saved)
        self.assertEqual(result['risk_extension']['reason'],'base_risk_unavailable')

    def test_future_weights_are_not_used(self):
        base={'candidate':'cashcast-research-18','status':'research_only','as_of':'2026-01-01',
              'risk':{'new_gap_warning':False}}
        result=DiverseAddon.apply(base,{'input':{'as_of':'2026-01-01'}},
                                  {'models':{'2026-01-31':[]}},Path('.'))
        self.assertEqual(result['risk_extension']['reason'],'no_causal_checkpoint')

    def test_reject_changed_mixing_weight_or_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'manifest.json'
            original={'policy':'cashcast-research-29','threshold':.05,'cat_weight':.5,
                      'split':'sha256_byte0_mod5_holdout_byte1_mod5_group'}
            for change in ({'threshold':.025},{'cat_weight':.75}):
                path.write_text(json.dumps({**original,**change}),encoding='utf-8')
                with self.assertRaises(ValueError):DiverseAddon.manifest(path,Path(tmp)/'absent-base')


if __name__=='__main__':unittest.main()
