"""Демо-подключения: preview до записи планов; никаких запросов в банк, 1С или ФНС."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.external_sources import ExternalPreviewOut, ExternalSourcesOut, SourcePreviewRequest
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.core.errors import AppError
from app.modules.external_sources.adapters import MAX_BYTES, demo_bank, demo_onec, tax_csv, tax_template
from app.modules.external_sources.service import ExternalSourceImportService

router = APIRouter(tags=["external-sources"], responses=ERROR_RESPONSES)


@router.get("/companies/{company_id}/external-sources", response_model=ExternalSourcesOut)
def sources(company_id: uuid.UUID, _company: str = Depends(require_company_access)) -> ExternalSourcesOut:
    return ExternalSourcesOut(items=[
        {"id": "bank", "label": "Банк", "description": "Кредитный график, зарплата и неисполненные платёжки"},
        {"id": "onec", "label": "1С", "description": "Выставленные и полученные счета, платежи по договорам"},
        {"id": "tax", "label": "Налоговые документы",
         "description": "Загрузка демо-CSV с известными суммами и сроками"},
    ], warning="Все источники демонстрационные. Связи с банком, базой 1С и ФНС нет.")


@router.post("/companies/{company_id}/external-sources/{provider}/preview", response_model=ExternalPreviewOut)
def preview_source(
    company_id: uuid.UUID, provider: Literal["bank", "onec"], body: SourcePreviewRequest,
    _company: str = Depends(require_company_access), user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> ExternalPreviewOut:
    batch = demo_bank() if provider == "bank" else demo_onec()
    return ExternalPreviewOut(**ExternalSourceImportService(session).preview(
        company_id=company_id, account_id=body.account_id, user_id=uuid.UUID(user.id),
        as_of=body.as_of or datetime.now(UTC).date(), batch=batch,
    ))


@router.get("/companies/{company_id}/external-tax-template")
def download_tax_template(company_id: uuid.UUID, _company: str = Depends(require_company_access)) -> Response:
    return Response(tax_template(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="cashcast-demo-taxes.csv"'})


@router.post("/companies/{company_id}/external-tax-imports", response_model=ExternalPreviewOut)
def preview_tax(
    company_id: uuid.UUID, account_id: uuid.UUID = Form(...), file: UploadFile = File(...),
    _company: str = Depends(require_company_access), user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
) -> ExternalPreviewOut:
    limit = min(settings.max_upload_bytes, MAX_BYTES)
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise AppError(413, "file_too_large", "Файл превышает допустимый размер")
    return ExternalPreviewOut(**ExternalSourceImportService(session).preview(
        company_id=company_id, account_id=account_id, user_id=uuid.UUID(user.id),
        as_of=datetime.now(UTC).date(), batch=tax_csv(content),
    ))
