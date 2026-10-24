"""Только чтение истории расчётов со стабильной границей страницы и tenant context."""

import base64
import binascii
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, and_, cast, literal, select, tuple_
from sqlalchemy.orm import Session, load_only

from app.api.schemas.common import ERROR_RESPONSES, Page
from app.api.schemas.forecast_history import ForecastHistoryItem
from app.core.auth import require_company_access
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import Account, ForecastRun, Job

router = APIRouter(tags=["forecasts"], responses=ERROR_RESPONSES)


class ForecastHistoryCursor:
    """Курсор не выдаёт права доступа: company/account проверяются независимо."""

    @staticmethod
    def encode(run: ForecastRun, company_id: uuid.UUID, account_id: uuid.UUID) -> str:
        payload = {"v": 1, "company_id": str(company_id), "account_id": str(account_id),
                   "created_at": run.created_at.astimezone(UTC).isoformat(), "id": str(run.id)}
        return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")

    @staticmethod
    def decode(cursor: str, company_id: uuid.UUID, account_id: uuid.UUID) -> tuple[datetime, uuid.UUID]:
        try:
            if not cursor or len(cursor) > 1024:
                raise ValueError
            payload = json.loads(base64.b64decode(
                (cursor + "=" * (-len(cursor) % 4)).encode("ascii"), altchars=b"-_", validate=True,
            ))
            expected = {"v", "company_id", "account_id", "created_at", "id"}
            if (not isinstance(payload, dict) or set(payload) != expected
                    or type(payload["v"]) is not int or payload["v"] != 1
                    or payload["company_id"] != str(company_id) or payload["account_id"] != str(account_id)
                    or not isinstance(payload["created_at"], str) or not isinstance(payload["id"], str)):
                raise ValueError
            timestamp = datetime.fromisoformat(payload["created_at"])
            row_id = uuid.UUID(payload["id"])
            if timestamp.tzinfo is None or timestamp.utcoffset() is None or str(row_id) != payload["id"]:
                raise ValueError
            return timestamp.astimezone(UTC), row_id
        except (ValueError, TypeError, UnicodeError, binascii.Error, OverflowError):
            raise AppError(422, "invalid_cursor", "Некорректный курсор истории расчётов") from None


@router.get("/companies/{company_id}/forecasts", response_model=Page[ForecastHistoryItem])
def list_forecast_history(
    company_id: uuid.UUID, account_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100), cursor: str | None = None,
    _company: str = Depends(require_company_access),
    session: Session = Depends(get_db, scope="function"),
) -> Page[ForecastHistoryItem]:
    account = session.scalar(select(Account.id).where(
        Account.id == account_id, Account.company_id == company_id,
    ))
    if account is None:
        raise AppError(404, "not_found", "Счёт не найден")
    # Unique dedupe_key даёт не больше одного job. Чужой/не-forecast job не раскрывается.
    statement = select(ForecastRun, Job.id).options(load_only(
        ForecastRun.id, ForecastRun.account_id, ForecastRun.as_of, ForecastRun.horizon_days,
        ForecastRun.status, ForecastRun.model_version, ForecastRun.data_version, ForecastRun.seed,
        ForecastRun.base_forecast_id, ForecastRun.created_at, ForecastRun.error_code,
        # Даже limit100 не должен загружать полные input_snapshot/details из JSONB.
        raiseload=True,
    )).outerjoin(Job, and_(
        Job.dedupe_key == literal("forecast:") + cast(ForecastRun.id, String),
        Job.company_id == ForecastRun.company_id, Job.kind == "forecast",
    )).where(ForecastRun.company_id == company_id, ForecastRun.account_id == account_id)
    if cursor is not None:
        boundary = ForecastHistoryCursor.decode(cursor, company_id, account_id)
        statement = statement.where(tuple_(ForecastRun.created_at, ForecastRun.id) < boundary)
    rows = session.execute(statement.order_by(
        ForecastRun.created_at.desc(), ForecastRun.id.desc(),
    ).limit(limit + 1)).all()
    has_more, rows = len(rows) > limit, rows[:limit]
    return Page(items=[ForecastHistoryItem(
        id=run.id, account_id=run.account_id, as_of=run.as_of, horizon_days=run.horizon_days,
        status=run.status, model_version=run.model_version, data_version=run.data_version,
        seed=run.seed, base_forecast_id=run.base_forecast_id, created_at=run.created_at,
        error_code=run.error_code, job_id=job_id,
    ) for run, job_id in rows], next_cursor=ForecastHistoryCursor.encode(
        rows[-1][0], company_id, account_id,
    ) if has_more else None)
