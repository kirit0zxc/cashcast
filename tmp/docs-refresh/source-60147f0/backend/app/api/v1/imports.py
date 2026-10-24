"""Загрузка выписки: preview и commit."""

from __future__ import annotations

import dataclasses
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.api.schemas.models import ColumnMappingIn, ImportCommitResponse, ImportPreviewResponse
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.company_access import CompanyAccess
from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import Account
from app.modules.imports.parser import ColumnMapping
from app.modules.imports.service import ImportService

router = APIRouter(tags=["imports"], responses=ERROR_RESPONSES)


@router.post("/companies/{company_id}/imports", response_model=ImportPreviewResponse,
             responses={413: {"model": ErrorResponse, "description": "Файл превышает допустимый размер"}})
def create_import(
    company_id: uuid.UUID,
    account_id: uuid.UUID = Form(...),
    mapping: str = Form(..., description="JSON соответствия колонок (ColumnMappingIn)"),
    file: UploadFile = File(...),
    _company: str = Depends(require_company_access),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings),
) -> ImportPreviewResponse:
    # Sync endpoint выполняется в threadpool: SQL/CSV не блокируют ASGI loop,
    # который должен завершать commit другого запроса и освобождать account lock.
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise AppError(413, "file_too_large", "Файл превышает допустимый размер")

    acc = session.get(Account, account_id)
    if acc is None or str(acc.company_id) != str(company_id):
        raise AppError(404, "not_found", "Счёт не найден")

    try:
        mapping_in = ColumnMappingIn.model_validate_json(mapping)
    except ValidationError:
        raise AppError(422, "invalid_mapping", "Некорректное соответствие колонок CSV") from None
    col_map = ColumnMapping(**mapping_in.model_dump())
    result = ImportService(session).preview(
        company_id=str(company_id),
        account_id=str(account_id),
        filename=file.filename or "statement.csv",
        content=content,
        mapping=col_map,
        uploaded_by=user.id,
    )
    return ImportPreviewResponse(**dataclasses.asdict(result))


@router.post("/imports/{import_id}/commit", response_model=ImportCommitResponse)
def commit_import(
    import_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> ImportCommitResponse:
    from app.core.models import StatementImport

    imp = session.get(StatementImport, import_id)
    if imp is None:
        raise AppError(404, "not_found", "Импорт не найден")
    _require_member(session, user.id, str(imp.company_id))
    result = ImportService(session).commit(company_id=str(imp.company_id), import_id=str(import_id))
    return ImportCommitResponse(**result)


def _require_member(session: Session, user_id: str, company_id: str) -> None:
    CompanyAccess(session).require(user_id, company_id, write=True)
