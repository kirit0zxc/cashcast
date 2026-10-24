"""Сравнение только совместимых успешных снимков: сценарий минус исходная база."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.comparisons import ComparedPoint, ComparedRisk, ForecastComparison
from app.api.v1.forecasts import _require_member, get_forecast
from app.core.auth import CurrentUser, get_current_user
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import ForecastRun

router = APIRouter(tags=["comparisons"], responses=ERROR_RESPONSES)


@router.get("/forecasts/{forecast_id}/comparison", response_model=ForecastComparison)
def compare_forecasts(forecast_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                     session: Session = Depends(get_db, scope="function")) -> ForecastComparison:
    scenario = session.get(ForecastRun, forecast_id)
    if scenario is None:
        raise AppError(404, "not_found", "Прогноз не найден")
    _require_member(session, user.id, str(scenario.company_id))
    if scenario.base_forecast_id is None:
        raise AppError(409, "not_a_scenario", "Для сравнения выберите сценарий")
    base = session.get(ForecastRun, scenario.base_forecast_id)
    if base is None or scenario.status != "succeeded" or base.status != "succeeded":
        raise AppError(409, "forecast_not_ready", "Дождитесь успешного расчёта базы и сценария")
    keys = ("company_id", "account_id", "as_of", "horizon_days", "data_version", "model_version", "seed")
    if any(getattr(base, k) != getattr(scenario, k) for k in keys):
        raise AppError(409, "incompatible_forecasts", "Прогнозы имеют разные исходные условия")
    original = get_forecast(base.id, user, session)
    changed = get_forecast(scenario.id, user, session)
    if len(original.points) != base.horizon_days or [p.point_date for p in original.points] != [
        p.point_date for p in changed.points
    ]:
        raise AppError(409, "incompatible_forecasts", "Не совпадают даты прогнозов")
    return ForecastComparison(
        base_forecast_id=str(base.id), scenario_forecast_id=str(scenario.id), as_of=base.as_of,
        horizon_days=base.horizon_days, model_version=base.model_version,
        points=[ComparedPoint(
            point_date=a.point_date, base_balance_p50_minor=a.balance_p50_minor,
            scenario_balance_p50_minor=b.balance_p50_minor,
            delta_balance_minor=b.balance_p50_minor - a.balance_p50_minor,
        ) for a, b in zip(original.points, changed.points, strict=True)],
        risk=ComparedRisk(base=original.risk, scenario=changed.risk),
    )
