"""Читаемый пульс конкретного frozen-прогноза с той же изоляцией компаний."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.pulse import PulseOut
from app.core.auth import CurrentUser, get_current_user
from app.core.company_access import CompanyAccess
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.forecast_input import ForecastInputCodec
from app.core.models import ForecastPoint, ForecastRun
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR, ForecastInputError
from app.modules.pulse.frozen import FrozenPulseService

router = APIRouter(tags=["pulse"], responses=ERROR_RESPONSES)


@router.get("/forecasts/{forecast_id}/pulse", response_model=PulseOut)
def get_pulse(
    forecast_id: uuid.UUID,
    buffer_minor: int | None = Query(default=None, ge=0, le=MAX_MONEY_MINOR),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> PulseOut:
    run = session.get(ForecastRun, forecast_id)
    if run is None:
        raise AppError(404, "not_found", "Прогноз не найден")
    CompanyAccess(session).require(user.id, str(run.company_id))
    if run.status != "succeeded":
        raise AppError(409, "forecast_not_ready", "Дождитесь успешного расчёта прогноза")
    try:
        data = ForecastInputCodec.decode(run.input_snapshot or {})
    except (KeyError, ValueError, TypeError):
        raise AppError(409, "pulse_source_unavailable", "У этого прогноза нет полного сохранённого входа") from None
    if (
        data.account_id != str(run.account_id)
        or data.as_of != run.as_of
        or data.horizon_days != run.horizon_days
        or data.opening_balance_minor != run.opening_balance_minor
    ):
        raise AppError(409, "pulse_source_unavailable", "Сохранённый вход не соответствует прогнозу")
    points = session.scalars(
        select(ForecastPoint)
        .where(
            ForecastPoint.forecast_run_id == run.id,
        )
        .order_by(ForecastPoint.point_date)
    ).all()
    try:
        result = FrozenPulseService.build(
            data,
            points,
            run.details or {},
            company_id=str(run.company_id),
            buffer_minor=buffer_minor,
            warnings=run.data_warnings,
        )
    except ForecastInputError as error:
        raise AppError(422, error.code, "Сохранённые данные не подходят для пульса") from None
    return PulseOut.model_validate(
        {
            **result,
            "forecast_id": str(run.id),
            "account_id": str(run.account_id),
            "model_version": run.model_version,
            "data_version": run.data_version,
        }
    )
