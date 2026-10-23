"""Запрос прогноза (202 + job), статус задания, получение прогноза, объяснения и сценарии."""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.models import (
    ExplanationsOut,
    ForecastOut,
    ForecastPointOut,
    ForecastRequest,
    JobAccepted,
    JobStatusOut,
    RiskOut,
    ScenarioRequest,
)
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.core.errors import AppError, not_implemented
from app.core.models import Account, ForecastPoint, ForecastRun, Job
from app.modules.forecasting.baseline import MODEL_VERSION
from app.modules.forecasting.snapshot import build_snapshot
from app.modules.jobs import queue

router = APIRouter(tags=["forecasts"], responses=ERROR_RESPONSES)


@router.post("/companies/{company_id}/forecasts", response_model=JobAccepted, status_code=202)
def create_forecast(
    company_id: uuid.UUID,
    body: ForecastRequest,
    response: Response,
    _company: str = Depends(require_company_access),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobAccepted:
    acc = session.get(Account, uuid.UUID(body.account_id))
    if acc is None or str(acc.company_id) != str(company_id):
        raise AppError(404, "not_found", "Счёт не найден")
    seed = body.seed if body.seed is not None else settings.forecast_default_seed

    # Собираем снимок только ради data_version — чтобы повторный запрос нашёл тот же прогон.
    snap = build_snapshot(
        session,
        account_id=body.account_id,
        as_of=body.as_of,
        horizon_days=body.horizon_days,
        seed=seed,
    )
    run = _get_or_create_run(
        session,
        company_id=company_id,
        account_id=uuid.UUID(body.account_id),
        as_of=body.as_of,
        horizon_days=body.horizon_days,
        data_version=snap.data_version,
        seed=seed,
        created_by=uuid.UUID(user.id),
    )
    job = queue.enqueue(
        session,
        kind="forecast",
        payload={"forecast_run_id": str(run.id)},
        company_id=str(company_id),
        dedupe_key=f"forecast:{run.id}",
    )
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return JobAccepted(job_id=str(job.id), forecast_run_id=str(run.id), status=job.status)


@router.get("/jobs/{job_id}", response_model=JobStatusOut)
def get_job(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> JobStatusOut:
    job = session.get(Job, job_id)
    if job is None:
        raise AppError(404, "not_found", "Задание не найдено")
    if job.company_id is not None:
        _require_member(session, user.id, str(job.company_id))
    run_id = (job.payload or {}).get("forecast_run_id")
    return JobStatusOut(
        id=str(job.id),
        kind=job.kind,
        status=job.status,
        forecast_run_id=run_id,
        error_code=job.last_error,
    )


@router.get("/forecasts/{forecast_id}", response_model=ForecastOut)
def get_forecast(
    forecast_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ForecastOut:
    run = session.get(ForecastRun, forecast_id)
    if run is None:
        raise AppError(404, "not_found", "Прогноз не найден")
    _require_member(session, user.id, str(run.company_id))
    points = session.scalars(
        select(ForecastPoint)
        .where(ForecastPoint.forecast_run_id == run.id)
        .order_by(ForecastPoint.point_date)
    ).all()
    return ForecastOut(
        id=str(run.id),
        account_id=str(run.account_id),
        as_of=run.as_of,
        horizon_days=run.horizon_days,
        status=run.status,
        model_version=run.model_version or MODEL_VERSION,
        data_version=run.data_version,
        seed=run.seed,
        opening_balance_minor=run.opening_balance_minor,
        base_forecast_id=str(run.base_forecast_id) if run.base_forecast_id else None,
        assumptions=run.assumptions,
        data_warnings=run.data_warnings,
        risk=RiskOut(
            available=run.risk_available,
            first_negative_date=run.first_negative_date,
            max_deficit_minor=run.max_deficit_minor,
            probability_any_negative=run.probability_any_negative,
        ),
        points=[
            ForecastPointOut(
                point_date=p.point_date,
                inflow_minor=p.inflow_minor,
                outflow_minor=p.outflow_minor,
                balance_p10_minor=p.balance_p10_minor,
                balance_p50_minor=p.balance_p50_minor,
                balance_p90_minor=p.balance_p90_minor,
                probability_negative=p.probability_negative,
            )
            for p in points
        ],
    )


@router.get("/forecasts/{forecast_id}/explanations", response_model=ExplanationsOut)
def get_explanations(
    forecast_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ExplanationsOut:
    run = session.get(ForecastRun, forecast_id)
    if run is None:
        raise AppError(404, "not_found", "Прогноз не найден")
    _require_member(session, user.id, str(run.company_id))
    # Разбор причин риска по источникам — зона Данила/Димы. Контракт готов, реализации нет.
    raise not_implemented("Данил/Дима")


@router.post("/forecasts/{forecast_id}/scenarios", response_model=JobAccepted, status_code=202)
def create_scenario(
    forecast_id: uuid.UUID,
    body: ScenarioRequest,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobAccepted:
    base = session.get(ForecastRun, forecast_id)
    if base is None:
        raise AppError(404, "not_found", "Базовый прогноз не найден")
    _require_member(session, user.id, str(base.company_id))

    seed = body.seed if body.seed is not None else base.seed
    # mode="json": даты -> ISO-строки, чтобы и JSONB-колонка, и хеш сериализовались одинаково.
    changes = [c.model_dump(mode="json", exclude_none=True) for c in body.changes]
    scenario = {"changes": changes}
    scenario_hash = hashlib.sha256(
        json.dumps(scenario, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    run = _get_or_create_run(
        session,
        company_id=base.company_id,
        account_id=base.account_id,
        as_of=base.as_of,
        horizon_days=base.horizon_days,
        data_version=base.data_version,
        seed=seed,
        created_by=uuid.UUID(user.id),
        scenario=scenario,
        scenario_hash=scenario_hash,
        base_forecast_id=base.id,
    )
    job = queue.enqueue(
        session,
        kind="forecast",
        payload={"forecast_run_id": str(run.id)},
        company_id=str(base.company_id),
        dedupe_key=f"forecast:{run.id}",
    )
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return JobAccepted(job_id=str(job.id), forecast_run_id=str(run.id), status=job.status)


def _get_or_create_run(
    session: Session,
    *,
    company_id,
    account_id,
    as_of,
    horizon_days,
    data_version,
    seed,
    created_by,
    scenario=None,
    scenario_hash="",
    base_forecast_id=None,
) -> ForecastRun:
    # Повтор того же входа (вкл. сценарий) не плодит прогоны — возвращаем существующий.
    existing = session.scalar(
        select(ForecastRun).where(
            ForecastRun.account_id == account_id,
            ForecastRun.as_of == as_of,
            ForecastRun.horizon_days == horizon_days,
            ForecastRun.data_version == data_version,
            ForecastRun.model_version == MODEL_VERSION,
            ForecastRun.seed == seed,
            ForecastRun.scenario_hash == scenario_hash,
        )
    )
    if existing is not None:
        return existing
    run = ForecastRun(
        company_id=company_id,
        account_id=account_id,
        as_of=as_of,
        horizon_days=horizon_days,
        data_version=data_version,
        model_version=MODEL_VERSION,
        seed=seed,
        scenario_hash=scenario_hash,
        scenario=scenario,
        base_forecast_id=base_forecast_id,
        status="pending",
        created_by=created_by,
    )
    session.add(run)
    session.flush()
    return run


def _require_member(session: Session, user_id: str, company_id: str) -> None:
    from app.core.models import CompanyMember

    if session.get(
        CompanyMember, {"company_id": uuid.UUID(company_id), "user_id": uuid.UUID(user_id)}
    ) is None:
        raise AppError(404, "not_found", "Прогноз не найден")
