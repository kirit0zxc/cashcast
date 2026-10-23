"""Обработчики заданий. Пока один: расчёт прогноза (baseline). Данил заменит модель внутри.

Обработчик читает ForecastRun по id из payload, собирает снимок, запускает ForecastService,
сохраняет точки и риск в снимок. Категории/регулярности сейчас не влияют на baseline, но
снимок уже готов их принять (поля в ForecastInput есть).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.models import ForecastPoint, ForecastRun
from app.modules.contracts import ScenarioChange
from app.modules.forecasting.service import get_forecast_service
from app.modules.forecasting.snapshot import build_snapshot


def handle_forecast(session: Session, payload: dict) -> dict:
    run_id = payload["forecast_run_id"]
    run = session.get(ForecastRun, run_id)
    if run is None:
        # Снимок удалён — задание бессмысленно; считаем выполненным, чтобы не циклить повтор.
        return {"skipped": "forecast_run_missing"}

    run.status = "running"
    session.flush()

    scenario = _parse_scenario(run.scenario)
    snap = build_snapshot(
        session,
        account_id=str(run.account_id),
        as_of=run.as_of,
        horizon_days=run.horizon_days,
        seed=run.seed,
        scenario=scenario,
    )
    result = get_forecast_service().run(snap.data)

    # Чистим прежние точки (повторный расчёт того же снимка перезаписывает результат).
    session.query(ForecastPoint).filter(ForecastPoint.forecast_run_id == run.id).delete()
    for p in result.points:
        session.add(
            ForecastPoint(
                forecast_run_id=run.id,
                point_date=p.point_date,
                inflow_minor=p.inflow_minor,
                outflow_minor=p.outflow_minor,
                balance_p10_minor=p.balance_p10_minor,
                balance_p50_minor=p.balance_p50_minor,
                balance_p90_minor=p.balance_p90_minor,
                probability_negative=p.probability_negative,
            )
        )

    run.model_version = result.model_version
    run.opening_balance_minor = snap.opening_balance_minor
    run.assumptions = result.assumptions
    run.data_warnings = [*snap.warnings, *result.data_warnings]
    run.risk_available = result.risk.available
    run.first_negative_date = result.risk.first_negative_date
    run.max_deficit_minor = result.risk.max_deficit_minor
    run.probability_any_negative = result.risk.probability_any_negative
    run.details = result.details
    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    session.flush()
    return {"forecast_run_id": str(run.id), "points": len(result.points)}


def _parse_scenario(scenario: dict | None) -> list[ScenarioChange]:
    # on_date хранится в JSONB как ISO-строка — возвращаем обратно в date для расчёта.
    if not scenario:
        return []
    changes: list[ScenarioChange] = []
    for raw in scenario.get("changes", []):
        data = dict(raw)
        if isinstance(data.get("on_date"), str):
            data["on_date"] = date.fromisoformat(data["on_date"])
        changes.append(ScenarioChange(**data))
    return changes


# Реестр обработчиков по виду задания. Новые виды добавляются сюда.
HANDLERS = {"forecast": handle_forecast}
