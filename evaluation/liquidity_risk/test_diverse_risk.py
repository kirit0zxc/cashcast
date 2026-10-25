"""Замороженная смесь, ранние границы выбора и неизменный парный baseline."""
import unittest
from copy import deepcopy

from evaluation.fallback_model.data import Dataset
from .diverse_risk import DiversePolicy, DiverseExperiment


class DiverseTests(unittest.TestCase):
    def rows(self):
        company = next('test'+str(i) for i in range(100) if not Dataset.heldout('test'+str(i)))
        base = dict(company=company, phase='validation', cutoff='2026-01-31', current=.6,
                    risk18=False, risk21=True, risk25=True, score25=.1)
        return [{**base, 'label': True, 'cat_score': .1} for _ in range(5)]+[
            {**base, 'label': False, 'cat_score': .001}]

    def test_fixed_equal_mix_and_no_unknown_modes(self):
        row = {'cat_score': .8, 'score25': .2}
        self.assertEqual(DiversePolicy.score(row, 'mean50'), .5)
        with self.assertRaises(ValueError): DiversePolicy.score(row, 'fit_late')

    def test_choose_early_less_fp_and_keep_original_on_tie(self):
        rows = self.rows()
        choice = DiversePolicy.choose(rows)['selected']
        self.assertEqual((choice['mode'], choice['threshold']), ('cat', .025))
        for row in rows: row['cat_score'] = row['score25']
        self.assertEqual(DiversePolicy.choose(rows)['selected']['mode'], 'keep25')

    def test_reject_late_or_heldout_and_keep_with_small_support(self):
        rows = self.rows()
        self.assertEqual(DiversePolicy.choose(rows[:4])['selected']['mode'], 'keep25')
        heldout = next('test'+str(i) for i in range(100) if Dataset.heldout('test'+str(i)))
        for change in ({'company': heldout}, {'phase': 'late_other'}, {'cutoff': '2026-07-31'}):
            with self.assertRaises(ValueError): DiversePolicy.choose([{**r, **change} for r in rows])

    def test_bootstrap_preserves_input_and_uses_requested_baseline(self):
        rows = self.rows(); original = deepcopy(rows)
        result = DiverseExperiment.bootstrap(rows, {'mode': 'cat', 'threshold': .025}, 'risk25')
        self.assertEqual(rows, original)
        self.assertEqual(result['differences']['fp']['point'], -1.)
        self.assertEqual(result['differences']['tp']['point'], 0.)


if __name__ == '__main__': unittest.main()
