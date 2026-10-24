"""Приоритет дополнительного разрыва и запрет скрывать месячные ухудшения."""
import unittest
from .recall_first import RecallPolicy


class RecallFirstTests(unittest.TestCase):
    @staticmethod
    def rows():
        return [{'company':str(i),'cutoff':'2026-01-31','current':i<4 or i==5,
                 'current_probability':.9 if i<4 or i==5 else .2 if i==4 else .01,
                 'chronos':i<4,'reserve':.6 if i<5 else .001,'label':i<5} for i in range(20)]

    def test_additional_tp_preferred(self):
        choice=RecallPolicy.choose(self.rows())['selected']
        self.assertEqual(choice['statistics']['tp'],5)
        self.assertEqual(choice['statistics']['fp'],0)
        self.assertLess(choice['current_threshold'],.5)

    def test_sparse_event_count_stays_current(self):
        rows=self.rows()[1:]
        self.assertEqual(RecallPolicy.choose(rows)['selected']['rule'],'current')

    def test_monthly_false_alarm_guard(self):
        rows=self.rows()
        rows.append({'company':'extra','cutoff':'2026-02-28','current':False,'current_probability':.2,
                     'chronos':True,'reserve':.9,'label':False})
        choice=RecallPolicy.choose(rows)['selected']
        # Дешёвая новая тревога во втором месяце недопустима при нулевом исходномFP.
        self.assertEqual(choice['statistics']['tp'],4)
        self.assertEqual(choice['current_threshold'],.5)


if __name__=='__main__':unittest.main()
