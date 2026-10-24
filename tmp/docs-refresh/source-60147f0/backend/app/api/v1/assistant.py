"""HTTP граница чата: сессия/CSRF, выбранный счёт и отдельное подтверждение человеком."""

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas.assistant import ActionDecision, ChatRequest, ChatResponse
from app.api.schemas.common import ERROR_RESPONSES
from app.api.v1.accounts import import_presets
from app.api.v1.imports import create_import
from app.api.v1.obligations import preview_obligations
from app.core.auth import CurrentUser, get_current_user
from app.core.company_access import CompanyAccess
from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.modules.assistant.actions import ActionService
from app.modules.assistant.gateway import SiteGateway
from app.modules.assistant.service import AssistantService

router = APIRouter(tags=["assistant"], responses=ERROR_RESPONSES)


@router.get("/assistant/status")
def status(user: CurrentUser = Depends(get_current_user), settings: Settings = Depends(get_settings)) -> dict:
    return {"enabled": bool(settings.openrouter_api_key.get_secret_value()), "model": settings.assistant_model}


@router.post("/companies/{company_id}/assistant/chat", response_model=ChatResponse)
def chat(company_id: uuid.UUID, body: ChatRequest, user: CurrentUser = Depends(get_current_user),
         session: Session = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings)):
    gateway = SiteGateway(session, user, company_id, body.account_id, settings)
    return AssistantService(gateway).chat(body)


@router.post("/companies/{company_id}/accounts/{account_id}/assistant/actions/{action_id}",
             response_model=ChatResponse)
def decide(company_id: uuid.UUID, account_id: uuid.UUID, action_id: uuid.UUID, body: ActionDecision,
           user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_db, scope="function"),
           settings: Settings = Depends(get_settings)):
    return ActionService(SiteGateway(session, user, company_id, account_id, settings)).decide(action_id, body.decision)


@router.post("/companies/{company_id}/accounts/{account_id}/assistant/uploads", response_model=ChatResponse)
def upload(company_id: uuid.UUID, account_id: uuid.UUID,
           import_kind: Literal["statement", "obligations"] = Form(...), file: UploadFile = File(...),
           mapping: str | None = Form(None), source_name: str = Form("assistant", min_length=1, max_length=40),
           as_of: date | None = Form(None, ge=date(2, 1, 2)), user: CurrentUser = Depends(get_current_user),
           session: Session = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings)):
    gateway = SiteGateway(session, user, company_id, account_id, settings)
    CompanyAccess(session).require(user.id, company_id, write=True)
    common = {"company_id": company_id, "account_id": account_id, "file": file, "user": user,
              "session": session, "settings": settings, "_company": str(company_id)}
    if import_kind == "statement":
        mapping = mapping or import_presets(user).items[0].mapping.model_dump_json()
        preview = create_import(mapping=mapping, **common).model_dump(mode="json")
    else:
        preview = preview_obligations(source_name=source_name, as_of=as_of, **common).model_dump(mode="json")
    cards = [{"kind": "import", "title": "Проверка CSV без изменения операций", "data": preview}]
    if not preview["error_count"]:
        cards.append(ActionService(gateway).propose("propose_commit_import", {
            "import_id": preview["import_id"], "import_kind": import_kind,
        }))
    return {"text": "Файл проверен. Проверьте сводку и подтвердите импорт отдельной кнопкой.", "cards": cards}
