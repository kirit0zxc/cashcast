"""Фикстуры specs/examples/ должны валидироваться против схем ответов v1.

Так контракт и примеры не расходятся: если схема изменится, тест упадёт, пока не
перегенерируют фикстуры (python -m app.scripts.gen_fixtures).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api.schemas.models import ForecastOut, ImportPreviewResponse

EXAMPLES = Path(__file__).resolve().parents[2] / "specs" / "examples"

_SCHEMA_BY_FILE = {
    "forecast_with_gap.json": ForecastOut,
    "forecast_no_gap.json": ForecastOut,
    "forecast_insufficient_history.json": ForecastOut,
    "import_invalid_csv.json": ImportPreviewResponse,
}


@pytest.mark.parametrize("filename,schema", _SCHEMA_BY_FILE.items())
def test_fixture_matches_schema(filename: str, schema) -> None:
    data = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    data.pop("_note", None)  # пояснение «синтетические данные» — не часть схемы
    schema.model_validate(data)


def test_gap_fixture_has_negative_balance() -> None:
    data = json.loads((EXAMPLES / "forecast_with_gap.json").read_text(encoding="utf-8"))
    assert data["risk"]["available"] is True
    assert any(p["balance_p50_minor"] < 0 for p in data["points"])
