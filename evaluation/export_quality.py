"""Детерминированная упаковка опубликованных измерений для API, без CatBoost и raw-файлов."""

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "backend/app/modules/model_quality/report.json"
SOURCES = ("berka-risk-results.json", "risk-followup-results.json", "real-data-results.json")


class QualityReportBuilder:
    @staticmethod
    def divide(numerator, denominator):
        return numerator / denominator if denominator else None

    @classmethod
    def metrics(cls, row):
        tp, fp, fn, tn = (row[k] for k in ("tp", "fp", "fn", "tn"))
        total = tp + fp + fn + tn
        recall = cls.divide(tp, tp + fn)
        specificity = cls.divide(tn, tn + fp)
        values = {
            "precision": (cls.divide(tp, tp + fp), "TP / (TP + FP): доля верных предупреждений"),
            "recall": (recall, "TP / (TP + FN): доля найденных разрывов"),
            "f1": (cls.divide(2 * tp, 2 * tp + fp + fn), "Гармоническое среднее precision и recall"),
            "f2": (cls.divide(5 * tp, 5 * tp + fp + 4 * fn), "F-мера с повышенным весом recall"),
            "specificity": (specificity, "TN / (TN + FP)"),
            "false_positive_rate": (cls.divide(fp, tn + fp), "FP / (TN + FP)"),
            "accuracy": (cls.divide(tp + tn, total), "(TP + TN) / N; малоинформативна при редких разрывах"),
            "balanced_accuracy": (
                (recall + specificity) / 2 if recall is not None and specificity is not None else None,
                "Среднее recall и specificity",
            ),
            "mcc": (
                cls.divide(tp * tn - fp * fn, math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))),
                "Корреляция Мэтьюса по матрице ошибок",
            ),
            "prevalence": (cls.divide(tp + fn, total), "Доля окон с фактическим разрывом"),
            "roc_auc": (row.get("roc_auc"), "Площадь под ROC; не процент верных ответов"),
            "average_precision": (
                row.get("average_precision"), "Average precision: ступенчатый интеграл PR, не трапецеидальный PR-AUC"
            ),
            "brier": (row.get("brier"), "Средняя квадратичная ошибка оценки вероятности; меньше лучше"),
            "constant_brier": (row.get("constant_brier"), "Brier константы: частота разрыва на обучении"),
        }
        return {key: {"value": value, "definition": definition,
                      "unavailable_reason": "undefined_denominator_or_not_measured" if value is None else None}
                for key, (value, definition) in values.items()}

    @classmethod
    def build(cls, root=ROOT):
        evidence = []
        for name in SOURCES:
            # Git на Windows меняет LF на CRLF; хэш описывает нормализованный UTF-8 текст.
            raw = (root / "evaluation" / name).read_text(encoding="utf-8").encode("utf-8")
            evidence.append({"path": "evaluation/" + name, "sha256": hashlib.sha256(raw).hexdigest(),
                             "hash_format": "utf8_lf", "data": json.loads(raw)})
        risk, followup, _flows = (item["data"] for item in evidence)
        cohorts = []
        for name, row in risk["results"].items():
            uncertainty = followup.get("retrospective", {}).get(name, {}).get("v1_threshold_005", {}).get("uncertainty")
            cohorts.append({
                "name": name, "windows": row["folds"], "accounts": row["accounts"],
                "positive_windows": row["positives"], "positive_accounts": row["positive_accounts"],
                "threshold": risk["threshold"],
                "confusion_matrix": {k: row[k] for k in ("tp", "fp", "fn", "tn")},
                "metrics": cls.metrics(row), "uncertainty": uncertainty,
            })
        return {
            "report_version": "model-quality-1.0", "scope": "offline_external_evaluation",
            "evaluated_model": risk["model"], "production_activated": False,
            "applies_to_current_forecast": False, "probability_calibrated": False, "horizon_days": 30,
            "label_definition": (
                "Новый отрицательный остаток на конец дня в следующие 30 дней при начальном остатке >= 0"
            ),
            "cohorts": cohorts, "calibration": followup["calibration"],
            "selection_policy": {"minimum_positives": 10, "minimum_precision": 0.5, "minimum_recall": 0.5,
                                 "maximum_false_positive_rate": 0.01, "selected": followup["selected"],
                                 "checks": followup["selection"]},
            "release": followup["release"], "evidence": evidence,
            "limitations": [
                "Это офлайн-отчёт исследовательских моделей, а не качество текущего прогноза вашего счёта.",
                "Berka: розничные счета 1990-х; нет подтверждения переноса на современные МСП.",
                "1998 уже изучался: повторная оценка ретроспективная, не новый независимый тест.",
                "Окна одного счёта зависимы; доверительные интервалы рассчитаны bootstrap по счетам.",
                "MoneyVis: один розничный счёт, нет положительных примеров нового разрыва; ROC-AUC недоступна.",
                "MAE MoneyVis указан в единицах исходной валюты, не в рублях; валюта не указана в CSV.",
                "Интервалы имеются только для метрик, фактически рассчитанных в uncertainty; null не означает ноль.",
                "Калибровка и критерии выпуска не пройдены. Числовая вероятность в продукте остаётся недоступной.",
            ],
        }

    @classmethod
    def write(cls):
        DESTINATION.write_text(json.dumps(cls.build(), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")


if __name__ == "__main__":
    QualityReportBuilder.write()
