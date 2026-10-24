"""Загрузка обязательств: авторизация/CSRF, предварительный просмотр, атомарное принятие."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.api.schemas.obligations import ObligationCommitOut, ObligationPreviewOut
from app.api.v1.imports import _require_member
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import ObligationImport
from app.modules.imports.obligations import ObligationImportService

router = APIRouter(tags=["obligation-imports"], responses=ERROR_RESPONSES)


@router.post("/companies/{company_id}/obligation-imports", response_model=ObligationPreviewOut,
             responses={413: {"model": ErrorResponse, "description": "Файл превышает допустимый размер"}})
def preview_obligations(
    company_id: uuid.UUID,
    account_id: uuid.UUID = Form(...),
    source_name: str = Form(..., min_length=1, max_length=40),
    as_of: date | None = Form(None, ge=date(2, 1, 2)),
    file: UploadFile = File(...),
    _company: str = Depends(require_company_access),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings),
) -> ObligationPreviewOut:
    limit = min(settings.max_upload_bytes, 10 * 1024 * 1024)
    # Чтение и синхронный SQL остаются в threadpool FastAPI, включая ожидание lock.
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise AppError(413, "file_too_large", "Файл превышает допустимый размер")
    result = ObligationImportService(session).preview(
        company_id=company_id, account_id=account_id, user_id=uuid.UUID(user.id),
        source_name=source_name, as_of=as_of or datetime.now(UTC).date(), content=content,
    )
    return ObligationPreviewOut(**result)


@router.post("/obligation-imports/{import_id}/commit", response_model=ObligationCommitOut)
def commit_obligations(
    import_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> ObligationCommitOut:
    imp = session.get(ObligationImport, import_id)
    if imp is None:
        raise AppError(404, "not_found", "Импорт не найден")
    _require_member(session, user.id, str(imp.company_id))
    return ObligationCommitOut(**ObligationImportService(session).commit(
        company_id=imp.company_id, import_id=import_id,
    ))
