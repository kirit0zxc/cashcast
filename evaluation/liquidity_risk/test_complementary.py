"""Проверяем логические сочетания, пороги и строгое сопоставление источников."""
import itertools
import unittest
import numpy as np
from .complementary import ComplementaryRisk as Risk


class ComplementaryTests(unittest.TestCase):
    def test_truth_tables(self):
        expected={"current":{4,5,6,7},"veto_union":{5,6,7},"majority":{3,5,6,7},
                  "union_intersection":{3,4,5,6,7},"chronos_union":{2,3,5,6,7}}
        for rule,positives in expected.items():
            for index,values in enumerate(itertools.product((False,True),repeat=3)):
                self.assertEqual(Risk.flag(*values,rule),index in positives)

    def test_join_checks_labels_and_duplicates(self):
        cdf=[{"company":"a","cutoff":"2026-01-31","current":.8,"scores":{"cdf6":{"30":.2}},"labels":{"30":True}}]
        forecasts=[{"company":"a","cutoff":"2026-01-31","opening":1,"probability":.8,
                    "truth":np.full((30,3),-1),"fallback":True,"intervals":{"ft100":np.ones((30,3))}}]
        self.assertTrue(Risk.join(cdf,forecasts)[0]["chronos"])
        with self.assertRaises(ValueError):Risk.join(cdf+cdf,forecasts)
        with self.assertRaises(ValueError):Risk.join(cdf,forecasts+forecasts)
        cdf[0]["labels"]["30"]=False
        with self.assertRaises(ValueError):Risk.join(cdf,forecasts)

    def test_selection_does_not_sacrifice_recall(self):
        rows=[{"company":str(i),"current":i<10,"chronos":i<4,"reserve":.2 if i==4 else .001,"label":i<5} for i in range(20)]
        selected=Risk.choose(rows)["selected"]
        self.assertEqual(selected["statistics"]["tp"],5)
        self.assertEqual(selected["statistics"]["fp"],0)
        self.assertIsNone(selected["statistics"]["probability_any_negative"])
        self.assertEqual(Risk.choose(rows[1:])["selected"]["rule"],"current")


if __name__=="__main__":unittest.main()
