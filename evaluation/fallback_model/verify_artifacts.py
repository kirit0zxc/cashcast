"""Проверка обученных артефактов и реального ForecastInput/ForecastResult без БД."""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.contracts import Direction, PlannedEventDTO, ScenarioChange, TxnDTO
from app.modules.forecasting.service import DEFAULT_MODEL_VERSION
from .adapter import LocalFallbackService
from .data import Dataset


class ArtifactVerifier:
    @staticmethod
    def run(source, artifacts):
        source_hashes = json.loads((ROOT / "journal/source-hashes-before-results.json").read_text(encoding="utf-8-sig"))
        for entry in source_hashes:
            original = entry["Path"].replace("\\", "/")
            relative = original.split("/cashcast-model-fallback/", 1)[-1]
            if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest().upper() != entry["Hash"]:
                raise AssertionError("Обучавшийся код изменился во время/после расчёта")
        windows, _ = Dataset(source).windows([date(2026, 8, 31)], date(2026, 9, 30))
        data, _, _ = next(item for item in windows if len(item[0].txns) > 200)
        safe = LocalFallbackService(artifacts).run(data)
        assert safe.model_version == DEFAULT_MODEL_VERSION, "Непрошедшая модель включилась по умолчанию"
        research = LocalFallbackService(artifacts, allow_unreleased=True)
        first = research.run(data)
        assert first.model_version == research.model_version
        assert len(first.points) == 30
        assert first.details["risk_probability"]["calibrated"] is False
        assert all(p.balance_p10_minor <= p.balance_p50_minor <= p.balance_p90_minor for p in first.points)
        assert first == research.run(data), "Повторная загрузка входа изменила прогноз"
        assert first == LocalFallbackService(artifacts, allow_unreleased=True).run(data), "Загрузка весов изменила результат"
        polluted = replace(data, txns=data.txns + [TxnDTO("future-extra", data.account_id, data.as_of + timedelta(days=1), 10**9, Direction.OUT)])
        assert first == research.run(polluted), "Будущая операция повлияла на прогноз"
        short = research.run(replace(data, horizon_days=7))
        assert first.points[:7] == short.points, "Смена горизонта изменила общий префикс"
        event = PlannedEventDTO("plan", Direction.OUT, 100, 100, data.as_of + timedelta(days=2), "planned", "invoice", "manual", data.as_of)
        planned = research.run(replace(data, planned_events=[event]))
        assert planned.model_version == DEFAULT_MODEL_VERSION, "Непроверенные планы попали в новую модель"
        scenario = research.run(replace(data, scenario=[ScenarioChange("add_expense", amount_minor=100, on_date=data.as_of + timedelta(days=2))]))
        assert scenario.model_version == DEFAULT_MODEL_VERSION
        if research.weight == 1:
            expected = data.opening_balance_minor + np.cumsum([p.inflow_minor-p.outflow_minor for p in first.points])
            np.testing.assert_array_equal(expected, [p.balance_p50_minor for p in first.points])
        result = {"status": "passed", "checks": 13, "sample_source": "organizer synthetic development account",
                  "production_default_unchanged": DEFAULT_MODEL_VERSION, "source_hashes_verified": True,
                  "forecast_sha256": hashlib.sha256(json.dumps(asdict(first), default=str, sort_keys=True).encode()).hexdigest()}
        (artifacts / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    ArtifactVerifier.run(args.zip, args.artifacts)
