"""Генерация JSON-фикстур в specs/examples/ из Pydantic-схем ответов.

Числа в фикстурах СИНТЕТИЧЕСКИЕ (поле _note в каждом файле). Из этих файлов Диана
поднимает MSW, Данил и Дима — тесты. Фикстуры валидируются тестом против схем v1.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.api.schemas.models import (
    ForecastOut,
    ForecastPointOut,
    ImportPreviewResponse,
    RiskOut,
)

OUT = Path(__file__).resolve().parents[3] / "specs" / "examples"
_NOTE = "СИНТЕТИЧЕСКИЕ данные для разработки фронтенда и тестов, не реальные измерения."


def _points(values: list[tuple[int, int, int, float | None]], start_day: int) -> list[dict]:
    # values: (inflow, outflow, balance_p50, prob_negative); p10/p90 ±10% для демо-разброса.
    from datetime import date, timedelta

    base = date(2026, 3, 1)
    points = []
    for i, (inflow, outflow, p50, prob) in enumerate(values, start=start_day):
        spread = abs(p50) // 10
        points.append(
            ForecastPointOut(
                point_date=base + timedelta(days=i),
                inflow_minor=inflow,
                outflow_minor=outflow,
                balance_p10_minor=p50 - spread,
                balance_p50_minor=p50,
                balance_p90_minor=p50 + spread,
                probability_negative=prob,
            ).model_dump(mode="json")
        )
    return points


def forecast_with_gap() -> dict:
    # Прогноз, где на 12-й день баланс уходит в минус.
    seq = []
    balance = 500000
    for _ in range(30):
        inflow, outflow = 50000, 80000
        balance += inflow - outflow
        prob = 0.0 if balance > 200000 else (0.3 if balance > 0 else 0.75)
        seq.append((inflow, outflow, balance, round(prob, 2)))
    out = ForecastOut(
        id="11111111-1111-1111-1111-111111111111",
        account_id="22222222-2222-2222-2222-222222222222",
        as_of="2026-03-01",
        horizon_days=30,
        status="succeeded",
        model_version="baseline-repeat-week-0.1",
        data_version="demo-sha",
        seed=42,
        opening_balance_minor=500000,
        base_forecast_id=None,
        assumptions=["Синтетический пример прогноза с кассовым разрывом."],
        data_warnings=[],
        risk=RiskOut(
            available=True,
            first_negative_date="2026-03-12",
            max_deficit_minor=190000,
            probability_any_negative=0.72,
        ),
        points=_points(seq, start_day=1),
    ).model_dump(mode="json")
    out["_note"] = _NOTE
    return out


def forecast_no_gap() -> dict:
    seq = []
    balance = 1_000_000
    for _ in range(30):
        inflow, outflow = 90000, 60000
        balance += inflow - outflow
        seq.append((inflow, outflow, balance, 0.0))
    out = ForecastOut(
        id="33333333-3333-3333-3333-333333333333",
        account_id="22222222-2222-2222-2222-222222222222",
        as_of="2026-03-01",
        horizon_days=30,
        status="succeeded",
        model_version="baseline-repeat-week-0.1",
        data_version="demo-sha-2",
        seed=42,
        opening_balance_minor=1_000_000,
        base_forecast_id=None,
        assumptions=["Синтетический пример: разрыва нет."],
        data_warnings=[],
        risk=RiskOut(
            available=True, first_negative_date=None, max_deficit_minor=None,
            probability_any_negative=0.02,
        ),
        points=_points(seq, start_day=1),
    ).model_dump(mode="json")
    out["_note"] = _NOTE
    return out


def forecast_insufficient_history() -> dict:
    # Истории мало: план показываем, оценку риска — нет.
    seq = [(0, 0, 500000, None) for _ in range(30)]
    out = ForecastOut(
        id="44444444-4444-4444-4444-444444444444",
        account_id="22222222-2222-2222-2222-222222222222",
        as_of="2026-03-01",
        horizon_days=30,
        status="succeeded",
        model_version="baseline-repeat-week-0.1",
        data_version="demo-sha-3",
        seed=42,
        opening_balance_minor=500000,
        base_forecast_id=None,
        assumptions=["Недостаточно истории для оценки неопределённости."],
        data_warnings=["Мало данных: показан плановый график, оценка риска недоступна."],
        risk=RiskOut(
            available=False, first_negative_date=None, max_deficit_minor=None,
            probability_any_negative=None,
        ),
        points=_points(seq, start_day=1),
    ).model_dump(mode="json")
    out["_note"] = _NOTE
    return out


def import_invalid_csv() -> dict:
    out = ImportPreviewResponse(
        import_id="55555555-5555-5555-5555-555555555555",
        status="failed",
        total_rows=2,
        error_count=2,
        duplicate_in_file=0,
        period_start=None,
        period_end=None,
        sample_errors=[
            {"row": 1, "field": "row", "message": "не распознана дата: 'вчера'"},
            {"row": 2, "field": "row", "message": "не распознана сумма: 'много'"},
        ],
        reused=False,
    ).model_dump(mode="json")
    out["_note"] = _NOTE
    return out


FIXTURES = {
    "forecast_with_gap.json": forecast_with_gap,
    "forecast_no_gap.json": forecast_no_gap,
    "forecast_insufficient_history.json": forecast_insufficient_history,
    "import_invalid_csv.json": import_invalid_csv,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, builder in FIXTURES.items():
        (OUT / name).write_text(
            json.dumps(builder(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"fixtures -> {OUT} (count: {len(FIXTURES)})")


if __name__ == "__main__":
    main()
