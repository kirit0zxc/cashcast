"""Самостоятельный детектор не сохраняет OR-базу скрыто и защищает TP по месяцам."""
import unittest
from .standalone_long_risk import StandalonePolicy
from . import test_diverse_risk as fixtures


class StandaloneTests(unittest.TestCase):
    def rows(self):
        return [{**r,'score31':r['score25'],'risk31':True,'risk18':True} for r in fixtures.DiverseTests().rows()]

    def test_can_remove_false_base_alert_without_losing_early_tp(self):
        rows=self.rows();choice=StandalonePolicy.choose(rows)['selected']
        self.assertEqual((choice['mode'],choice['threshold']),('cat',.005))
        self.assertEqual(StandalonePolicy.flags(rows,choice),[True]*5+[False])

    def test_recall_loss_cannot_be_hidden_by_fewer_false_positives(self):
        rows=self.rows()
        for row in rows:row['cat_score']=0.;row['score31']=0.
        self.assertEqual(StandalonePolicy.choose(rows)['selected']['mode'],'keep31')
        with self.assertRaises(ValueError):StandalonePolicy.choose([{**r,'phase':'late_other'} for r in rows])


if __name__=='__main__':unittest.main()
