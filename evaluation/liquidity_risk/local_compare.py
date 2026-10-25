"""Локальное сравнение снимка: независимые кривые, без подмены рабочего риска."""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.forecast_input import ForecastInputCodec
from app.modules.forecasting.service import get_forecast_service
from app.modules.forecasting.v2.quality import validate_input
from .chronos_trial import BalanceContext


class OfflineComparison:
    """Кандидат остаётся отдельным исследовательским результатом."""

    def __init__(self, metadata, pipeline=None):
        self.metadata = metadata
        self.pipeline = pipeline

    def load(self):
        if self.pipeline is None:
            import torch
            from chronos import Chronos2Pipeline
            torch.set_num_threads(4)
            torch.manual_seed(20261024)
            self.pipeline = Chronos2Pipeline.from_pretrained(
                self.metadata["snapshot"], device_map="cpu", local_files_only=True)
        return self.pipeline

    def run(self, snapshot):
        data = validate_input(snapshot)
        current = get_forecast_service().run(data)
        result = {
            "schema_version": 1, "production_activated": False,
            "as_of": data.as_of.isoformat(), "horizon_days": data.horizon_days,
            "unit": "RUB minor units", "current": {
                "model_version": current.model_version,
                "points": [asdict(p) for p in current.points],
                "risk": asdict(current.risk),
                "probability_calibrated": False,
            },
            "candidate": {"model": self.metadata["id"], "revision": self.metadata["revision"],
                          "status": "unavailable", "release_allowed": False,
                          "probability_any_negative": None, "points": []},
            "limits": ["Дневные квантили не являются вероятностью минуса за весь горизонт.",
                       "Кандидат не заменяет текущие предупреждения и не доказан на новом контрольном файле.",
                       "Точки Chronos — прогноз остатков; отдельные поступления и списания он здесь не прогнозирует."],
        }
        candidate = result["candidate"]
        if data.horizon_days != 30 or data.planned_events or data.scenario or data.recurrences:
            candidate["reason"] = "Исследован только горизонт 30 дней без явных планов, сценария и регулярностей DTO."
            return result
        context = BalanceContext.make(data)
        if context is None:
            candidate["reason"] = "Недостаточно согласованной истории для контекста модели."
            return result
        series, scale = context
        tensors, _ = self.load().predict_quantiles(
            [series.astype(np.float32)[None, :]], prediction_length=30,
            quantile_levels=[.1, .5, .9], batch_size=1, context_length=365,
            cross_learning=False)
        if len(tensors) != 1:
            raise ValueError("Неожиданное число прогнозов")
        raw = tensors[0].detach().cpu().numpy()
        if raw.shape != (1, 30, 3):
            raise ValueError("Неверная форма квантилей")
        values = np.sort(raw[0] * scale + data.opening_balance_minor, axis=1)
        if not np.isfinite(values).all() or np.max(abs(values)) > 9e15:
            raise ValueError("Нечисловой или слишком большой прогноз")
        # Вероятность текущей модели не приклеиваем к квантилям другого алгоритма.
        rounded = np.rint(values).astype(np.int64)
        candidate.update(status="research_only", warning_quantile=.1,
                         lower_bound_crosses_zero=bool(np.any(values[:, 0] < 0)),
                         opening_already_negative=data.opening_balance_minor < 0,
                         context_days=len(series))
        for index, row in enumerate(rounded):
            candidate["points"].append({
                "point_date": (data.as_of + timedelta(days=index + 1)).isoformat(),
                "balance_p10_minor": int(row[0]), "balance_p50_minor": int(row[1]),
                "balance_p90_minor": int(row[2]),
            })
        return result


class CompareCommand:
    @staticmethod
    def main():
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--model-info", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        snapshot = ForecastInputCodec.decode(json.loads(args.snapshot.read_text(encoding="utf-8")))
        metadata = json.loads(args.model_info.read_text(encoding="utf-8"))
        result = OfflineComparison(metadata).run(snapshot)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
        print("Локальное сравнение сохранено; приложение не изменялось.")


if __name__ == "__main__":
    CompareCommand.main()
