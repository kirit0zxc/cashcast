"""Границы переносимого дополнения: будущие веса и неподдержанный вход."""
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .rolling_runtime import RiskAddon


class RuntimeTests(unittest.TestCase):
    def test_future_model_never_selected(self):
        models={'2026-01-31':'a','2026-02-28':'b'}
        self.assertIsNone(RiskAddon.select_model(models,date(2026,1,30)))
        self.assertEqual(RiskAddon.select_model(models,date(2026,2,1)),'2026-01-31')

    def test_unavailable_base_is_not_silently_promoted(self):
        base={'candidate':'cashcast-research-18','status':'unavailable','current':[1]}
        result=RiskAddon.apply(base,{}, {},Path('.'))
        self.assertEqual(result['candidate'],'cashcast-research-18')
        self.assertEqual(result['risk_extension']['status'],'unavailable')
        self.assertNotIn('risk_extension',base)

    def test_already_negative_remains_inapplicable(self):
        base={'candidate':'cashcast-research-18','status':'research_only',
              'risk':{'status':'already_negative','new_gap_warning':None}}
        result=RiskAddon.apply(base,{}, {},Path('.'))
        self.assertIsNone(result['risk']['new_gap_warning'])
        self.assertEqual(result['risk']['status'],'already_negative')

    def test_date_mismatch_is_rejected(self):
        base={'candidate':'cashcast-research-18','status':'research_only','as_of':'2026-01-31',
              'risk':{'new_gap_warning':False}}
        with self.assertRaises(ValueError):RiskAddon.apply(base,{'input':{'as_of':'2026-02-28'}},{},Path('.'))

    def test_manifest_cannot_point_outside_addon(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base=root/'base.json';base.write_text('{}')
            manifest={'policy':'cashcast-research-21','threshold':.025,
                      'base_manifest_sha256':hashlib.sha256(base.read_bytes()).hexdigest(),
                      'files_sha256':{'../outside':'bad'}}
            p=root/'manifest.json';p.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'вне'):RiskAddon.manifest(p,base)


if __name__=='__main__':unittest.main()
