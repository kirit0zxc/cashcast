"""Счета доступной компании и явный пресет одиночной выписки организаторов."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.accounts import AccountList, AccountOut, ImportPreset, ImportPresetList
from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.models import ColumnMappingIn
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.deps import get_db
from app.core.models import Account

router = APIRouter(tags=["accounts"], responses=ERROR_RESPONSES)


@router.get("/companies/{company_id}/accounts", response_model=AccountList)
def list_accounts(
    company_id: uuid.UUID,
    _company: str = Depends(require_company_access),
    session: Session = Depends(get_db, scope="function"),
) -> AccountList:
    rows = session.scalars(
        select(Account).where(Account.company_id == company_id).order_by(Account.name, Account.id)
    ).all()
    return AccountList(items=[AccountOut(
        id=str(a.id), company_id=str(a.company_id), name=a.name, currency=a.currency,
    ) for a in rows])


@router.get("/import-presets", response_model=ImportPresetList)
def import_presets(_user: CurrentUser = Depends(get_current_user)) -> ImportPresetList:
    # Все настройки возвращаются явно: браузер не угадывает ни разделитель, ни колонки.
    return ImportPresetList(items=[ImportPreset(
        id="participants-v1", name="Выписка организаторов (одна компания)",
        mapping=ColumnMappingIn(
            date="operation_date", amount="amount", direction="direction",
            counterparty_name="counterparty_name", counterparty_ref="counterparty_inn",
            purpose="payment_purpose", external_id="operation_id", balance="balance_eod",
            delimiter=";", encoding="utf-8-sig",
        ),
    )])
