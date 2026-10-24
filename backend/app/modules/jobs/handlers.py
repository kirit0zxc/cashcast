"""Расчёт закреплённого входа прогноза и синхронизация окончательной ошибки с заданием."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.forecast_input import ForecastInputCodec
from app.core.models import ForecastPoint, ForecastRun
from app.modules.contracts import ScenarioChange
from app.modules.evaluation.service import handle_evaluation
from app.modules.forecasting.service import get_forecast_service
from app.modules.forecasting.v2.service import GuardedForecastService
from app.modules.jobs.incremental import ForecastCheckpointRepository


def handle_forecast(session: Session, payload: dict) -> dict:
    run_id = payload["forecast_run_id"]
    run = session.get(ForecastRun, run_id)
    if run is None:
        # Снимок удалён — задание бессмысленно; считаем выполненным, чтобы не циклить повтор.
        return {"skipped": "forecast_run_missing"}

    run.status = "running"
    session.flush()

    if not run.input_snapshot:
        raise ValueError("snapshot_unavailable")
    data = ForecastInputCodec.decode(run.input_snapshot)
    service = get_forecast_service(run.model_version)
    if isinstance(service, GuardedForecastService):
        state, source_id = ForecastCheckpointRepository(session).find(run, data)
        result = service.run(data, state=state)
        result.details["calculation"]["source_forecast_id"] = source_id
    else:
        result = service.run(data)
    if result.model_version != run.model_version:
        raise ValueError("pinned_model_unavailable")

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
    run.opening_balance_minor = data.opening_balance_minor
    run.assumptions = result.assumptions
    run.data_warnings = [*run.input_snapshot.get("warnings", []), *result.data_warnings]
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


def mark_forecast_failed(session: Session, payload: dict, error_code: str) -> None:
    """Неудача задания не оставляет связанный прогноз вечным pending/running."""
    try:
        run_id = UUID(str(payload.get("forecast_run_id")))
    except ValueError:
        return
    run = session.get(ForecastRun, run_id, with_for_update=True)
    if run is not None and run.status != "succeeded":
        run.status = "failed"
        run.error_code = error_code
        run.finished_at = datetime.now(UTC)


# Реестр обработчиков по виду задания. Новые виды добавляются сюда.
HANDLERS = {"forecast": handle_forecast, "evaluation": handle_evaluation}
