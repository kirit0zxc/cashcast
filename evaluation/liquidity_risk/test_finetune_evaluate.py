"""Выбор checkpoint не подменяет риск точечной ошибкой или нижним квантилем."""
import unittest
import numpy as np
from .finetune_evaluate import FineTuneEvaluation as Evaluation


class FineTuneSelectionTests(unittest.TestCase):
    @staticmethod
    def rows():
        rows = []
        for index in range(20):
            truth = np.zeros((30,3),dtype=np.int64)
            truth[:,2] = -100 if index<5 else 1000
            row = {"company":str(index),"cutoff":"2026-01-31","cohort":"established",
                   "truth":truth,"opening":1000,"probability":.9 if index<10 else .1,
                   "fallback":False,"models":{},"intervals":{}}
            for name, error in (("balance365",100),("ft100",50),("ft300",150),("current",200),("blend75",70)):
                prediction = truth.copy(); prediction[:,2] += error
                row["models"][name] = prediction
                row["intervals"][name] = np.full((30,3),-100 if index<6 else 100)
            rows.append(row)
        return rows

    def test_point_quality_and_recall_select_separately(self):
        rows = self.rows()
        for row in rows[:5]: row["intervals"]["ft100"][:] = 100
        selected = Evaluation.choose(rows,rows)
        self.assertEqual(selected["point"],"ft100")
        self.assertNotEqual(selected["risk"],"ft100")
        self.assertEqual(selected["risk_trials"][selected["risk"]]["tp"],5)

    def test_fallback_uses_current_flag(self):
        rows = self.rows()
        rows[0]["fallback"] = True
        rows[0]["intervals"]["ft100"][:] = 100
        self.assertEqual(Evaluation.risk(rows,"ft100")["tp"],5)

    def test_ties_and_sparse_positives_choose_current(self):
        rows = self.rows()
        for row in rows:
            for interval in row["intervals"].values():
                interval[:] = -1 if row["probability"]>=.5 else 1
        self.assertEqual(Evaluation.choose(rows,rows)["risk"],"current")
        self.assertEqual(Evaluation.choose(rows,rows[1:])["risk"],"current")

    def test_balance_models_do_not_claim_flow_scores(self):
        report = Evaluation.summarize(self.rows())
        score = report["scores"]["ft100"]["30"]
        self.assertNotIn("inflow_mae_rub",score)
        self.assertNotIn("probability",score)
        self.assertTrue(np.isfinite(score["pinball_rub"]))


if __name__ == "__main__": unittest.main()
