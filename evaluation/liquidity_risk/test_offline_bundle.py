"""Честная сборка выходов и отказ повреждённого локального артефакта."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from .offline_bundle import ArtifactManifest,OfflineCandidate


class OfflineTests(unittest.TestCase):
    @staticmethod
    def values():
        base=np.column_stack([np.full(30,10),np.full(30,5),100+np.arange(1,31)*5])
        stage={'supported':True,'current':base.tolist(),'direct':base.tolist(),'current_model':'test',
               'current_risk':{'probability_any_negative':.8},'as_of':'2026-01-01','opening':100,
               'fallback':False,'reserve_score':.2}
        quantiles=np.column_stack([np.full(30,-10),base[:,2]+2,base[:,2]+20]).tolist()
        return stage,{'original':quantiles,'finetuned':quantiles}

    def test_identity_and_no_fake_probability(self):
        stage,chrono=self.values();result=OfflineCandidate.combine(stage,chrono)
        values=np.array(result['reconciled_scenario'])
        np.testing.assert_array_equal(stage['opening']+np.cumsum(values[:,0]-values[:,1]),result['balance_minor'])
        self.assertTrue(result['risk']['new_gap_warning'])
        self.assertIsNone(result['risk']['probability_any_negative'])
        self.assertTrue((values[:,:2]>=0).all())

    def test_existing_negative_and_unavailable_not_false_success(self):
        stage,chrono=self.values();stage['opening']=-1
        result=OfflineCandidate.combine(stage,chrono)
        self.assertEqual(result['risk']['status'],'already_negative')
        self.assertIsNone(result['risk']['new_gap_warning'])
        stage.update(supported=False,reason='unsupported')
        result=OfflineCandidate.combine(stage,{})
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('balance_minor',result)

    def test_fallback_and_missing_probability(self):
        stage,_=self.values();stage['fallback']=True
        result=OfflineCandidate.combine(stage,{})
        self.assertTrue(result['fallback'])
        self.assertTrue(result['risk']['new_gap_warning'])
        stage['current_risk']['probability_any_negative']=None
        self.assertIsNone(OfflineCandidate.combine(stage,{})['risk']['new_gap_warning'])

    def test_unknown_manifest_and_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=root/'manifest.json';model=root/'model.cbm';model.write_bytes(b'weights')
            values={'schema_version':1,'policy':'cashcast-research-16','models':{n:'model.cbm' for n in ('direct','reserve','original','finetuned')},
                    'files_sha256':{'model.cbm':hashlib.sha256(b'weights').hexdigest()}}
            manifest.write_text(json.dumps(values));ArtifactManifest.load(manifest)
            model.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):ArtifactManifest.load(manifest)
            values['schema_version']=2;manifest.write_text(json.dumps(values))
            with self.assertRaises(ValueError):ArtifactManifest.load(manifest)

    def test_worker_failure_not_replaced_with_dummy(self):
        with patch('subprocess.run') as run:
            run.return_value.returncode=1
            with self.assertRaises(RuntimeError):OfflineCandidate.worker('python','tabular',{})


if __name__=='__main__':unittest.main()
