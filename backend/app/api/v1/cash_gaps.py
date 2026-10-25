"""Чтение карточки и проверка гипотез: не создают задания и не меняют планы."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.cash_gaps import CashGapOut, CashGapPreview
from app.api.schemas.common import ERROR_RESPONSES
from app.core.auth import CurrentUser, get_current_user
from app.core.company_access import CompanyAccess
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.forecast_input import ForecastInputCodec
from app.core.models import ForecastPoint, ForecastRun
from app.modules.cash_gaps.service import CashGapService
from app.modules.forecasting.v2.quality import ForecastInputError

router = APIRouter(tags=["cash-gaps"], responses=ERROR_RESPONSES)


class CashGapReader:
    @staticmethod
    def read(session, user, forecast_id, preview=None):
        run = session.get(ForecastRun, forecast_id)
        if run is None:
            raise AppError(404, "not_found", "Прогноз не найден")
        CompanyAccess(session).require(user.id, str(run.company_id))
        if run.status != "succeeded":
            raise AppError(409, "forecast_not_ready", "Дождитесь успешного расчёта прогноза")
        try:
            data = ForecastInputCodec.decode(run.input_snapshot or {})
        except (KeyError, ValueError, TypeError):
            raise AppError(409, "gap_source_unavailable", "Нет полного сохранённого входа прогноза") from None
        if (
            data.account_id != str(run.account_id)
            or data.as_of != run.as_of
            or data.horizon_days != run.horizon_days
            or data.opening_balance_minor != run.opening_balance_minor
        ):
            raise AppError(409, "gap_source_unavailable", "Вход не соответствует сохранённому прогнозу")
        points = session.scalars(
            select(ForecastPoint).where(ForecastPoint.forecast_run_id == run.id).order_by(ForecastPoint.point_date)
        ).all()
        try:
            result = CashGapService.build(
                data, points, run.details or {}, company_id=str(run.company_id), preview=preview
            )
        except ForecastInputError as error:
            raise AppError(422, error.code, "Некорректный сохранённый вход прогноза") from None
        result["warnings"] = list(dict.fromkeys([*result["warnings"], *(run.data_warnings or [])]))
        policy = (run.details or {}).get("risk_probability", {})
        if (preview is None and policy.get("status") == "estimated_uncalibrated"
                and run.probability_any_negative is not None):
            result.update(probability=run.probability_any_negative, probability_status="estimated_uncalibrated",
                          probability_reason=policy["reason"])
        elif preview is not None:
            result["probability_reason"] = (
                "Здесь изменяется только медианный остаток. Для вероятности после действия создайте отдельный сценарий."
            )
        elif policy.get("reason"):
            result["probability_reason"] = policy["reason"]
        return CashGapOut.model_validate(
            {**result, "forecast_id": str(run.id), "model_version": run.model_version, "data_version": run.data_version}
        )


@router.get("/forecasts/{forecast_id}/cash-gaps", response_model=CashGapOut)
def get_cash_gaps(
    forecast_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> CashGapOut:
    return CashGapReader.read(session, user, forecast_id)


@router.post("/forecasts/{forecast_id}/cash-gap-preview", response_model=CashGapOut)
def preview_cash_gaps(
    forecast_id: uuid.UUID,
    body: CashGapPreview,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> CashGapOut:
    # Viewer тоже может проверять гипотезы: endpoint не имеет побочных эффектов.
    # CSRF на POST проверяет общая зависимость get_current_user.
    return CashGapReader.read(session, user, forecast_id, body)
