"""Загрузка выписки: preview и commit."""

from __future__ import annotations

import dataclasses
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.models import ColumnMappingIn, ImportCommitResponse, ImportPreviewResponse
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import Account
from app.modules.imports.parser import ColumnMapping
from app.modules.imports.service import ImportService

router = APIRouter(tags=["imports"], responses=ERROR_RESPONSES)


@router.post("/companies/{company_id}/imports", response_model=ImportPreviewResponse)
async def create_import(
    company_id: uuid.UUID,
    account_id: str = Form(...),
    mapping: str = Form(..., description="JSON соответствия колонок (ColumnMappingIn)"),
    file: UploadFile = File(...),
    _company: str = Depends(require_company_access),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportPreviewResponse:
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise AppError(413, "file_too_large", "Файл превышает допустимый размер")

    acc = session.get(Account, uuid.UUID(account_id))
    if acc is None or str(acc.company_id) != str(company_id):
        raise AppError(404, "not_found", "Счёт не найден")

    try:
        mapping_in = ColumnMappingIn.model_validate_json(mapping)
    except ValidationError:
        raise AppError(422, "invalid_mapping", "Некорректное соответствие колонок CSV") from None
    col_map = ColumnMapping(**mapping_in.model_dump())
    result = ImportService(session).preview(
        company_id=str(company_id),
        account_id=account_id,
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
    session: Session = Depends(get_db),
) -> ImportCommitResponse:
    from app.core.models import StatementImport

    imp = session.get(StatementImport, import_id)
    if imp is None:
        raise AppError(404, "not_found", "Импорт не найден")
    _require_member(session, user.id, str(imp.company_id))
    result = ImportService(session).commit(company_id=str(imp.company_id), import_id=str(import_id))
    return ImportCommitResponse(**result)


def _require_member(session: Session, user_id: str, company_id: str) -> None:
    from app.core.models import CompanyMember

    member = session.get(
        CompanyMember, {"company_id": uuid.UUID(company_id), "user_id": uuid.UUID(user_id)}
    )
    if member is None:
        raise AppError(404, "not_found", "Импорт не найден")
