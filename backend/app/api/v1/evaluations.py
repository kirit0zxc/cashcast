"""Изолированная по компании проверка: enqueue, статус и скачиваемый отчёт."""

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.evaluation import EvaluationOut, EvaluationRequest
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.company_access import CompanyAccess
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import Job
from app.modules.evaluation.export import EvaluationExport
from app.modules.evaluation.service import CheckpointEvaluation
from app.modules.evaluation.snapshot import EvaluationSnapshot
from app.modules.jobs.queue import enqueue

router = APIRouter(tags=["evaluations"], responses=ERROR_RESPONSES)


@router.get("/companies/{company_id}/evaluations", response_model=list[EvaluationOut])
def list_evaluations(
    company_id: UUID,
    account_id: UUID,
    response: Response,
    _company: str = Depends(require_company_access),
    session: Session = Depends(get_db, scope="function"),
):
    # В списке только метаданные: большие отчёты читаются отдельно по ID.
    jobs = session.scalars(
        select(Job)
        .where(
            Job.company_id == company_id,
            Job.kind == "evaluation",
            Job.payload["account_id"].astext == str(account_id),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(20)
    ).all()
    response.headers["Cache-Control"] = "private, no-store"
    return [EvaluationOut(id=str(job.id), status=job.status, error_code=job.last_error) for job in jobs]


@router.post("/companies/{company_id}/evaluations", response_model=EvaluationOut, status_code=202)
def create_evaluation(
    company_id: UUID,
    body: EvaluationRequest,
    response: Response,
    _company: str = Depends(require_company_access),
    session: Session = Depends(get_db, scope="function"),
):
    payload = EvaluationSnapshot.build(session, company_id, body)
    job = enqueue(
        session,
        kind="evaluation",
        company_id=str(company_id),
        payload=payload,
        dedupe_key="evaluation:" + CheckpointEvaluation.fingerprint(payload),
        max_attempts=3,
    )
    # Явный повтор POST восстанавливает исчерпавшее попытки задание. Снимок тот же,
    # строка заблокирована: параллельные запросы не запускают две попытки одновременно.
    job = session.get(Job, job.id, with_for_update=True, populate_existing=True)
    if job.status == "failed":
        job.status = "pending"
        job.attempts = 0
        job.last_error = None
        job.locked_by = None
        job.lease_until = None
        job.result = None
        job.started_at = None
        job.finished_at = None
        job.run_after = datetime.now(UTC)
    response.headers["Location"] = f"/api/v1/evaluations/{job.id}"
    response.headers["Cache-Control"] = "private, no-store"
    return EvaluationOut(id=str(job.id), status=job.status, error_code=job.last_error)


def _require_job(session, user, evaluation_id):
    job = session.get(Job, evaluation_id)
    if job is None or job.kind != "evaluation" or job.company_id is None:
        raise AppError(404, "not_found", "Проверка не найдена")
    CompanyAccess(session).require(user.id, job.company_id)
    return job


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(
    evaluation_id: UUID,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
):
    job = _require_job(session, user, evaluation_id)
    response.headers["Cache-Control"] = "private, no-store"
    return EvaluationOut(
        id=str(job.id),
        status=job.status,
        error_code=job.last_error,
        report=job.result if job.status == "succeeded" else None,
    )


@router.get("/evaluations/{evaluation_id}/report", response_class=Response)
def export_evaluation(
    evaluation_id: UUID,
    format: Literal["json", "html"] = "json",
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
):
    job = _require_job(session, user, evaluation_id)
    if job.status != "succeeded" or not job.result:
        raise AppError(409, "evaluation_not_ready", "Дождитесь завершения проверки")
    content = (
        EvaluationExport.html(job.result)
        if format == "html"
        else json.dumps(job.result, ensure_ascii=False, indent=2, allow_nan=False)
    )
    return Response(
        content,
        media_type="text/html" if format == "html" else "application/json",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="cashcast-evaluation-{job.id}.{format}"',
        },
    )
