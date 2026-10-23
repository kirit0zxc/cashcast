"""Список операций с курсорной пагинацией и ручная правка категории."""

from __future__ import annotations

import base64
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES, Page
from app.api.schemas.models import TransactionCategoryPatch, TransactionOut
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import BankTransaction

router = APIRouter(tags=["transactions"], responses=ERROR_RESPONSES)


def _encode_cursor(booked_on: date, row_id: str) -> str:
    return base64.urlsafe_b64encode(f"{booked_on.isoformat()}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[date, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    d, row_id = raw.split("|", 1)
    return date.fromisoformat(d), row_id


@router.get("/companies/{company_id}/transactions", response_model=Page[TransactionOut])
def list_transactions(
    company_id: uuid.UUID,
    account_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    direction: str | None = Query(default=None, pattern="^(in|out)$"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    _company: str = Depends(require_company_access),
    session: Session = Depends(get_db),
) -> Page[TransactionOut]:
    stmt = select(BankTransaction).where(BankTransaction.company_id == company_id)
    if account_id:
        stmt = stmt.where(BankTransaction.account_id == uuid.UUID(account_id))
    if date_from:
        stmt = stmt.where(BankTransaction.booked_on >= date_from)
    if date_to:
        stmt = stmt.where(BankTransaction.booked_on <= date_to)
    if category:
        stmt = stmt.where(BankTransaction.category == category)
    if direction:
        stmt = stmt.where(BankTransaction.direction == direction)

    # Стабильный порядок для курсора: (booked_on, id). Курсор = последняя отданная пара.
    if cursor:
        c_date, c_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (BankTransaction.booked_on, BankTransaction.id) > (c_date, uuid.UUID(c_id))
        )
    stmt = stmt.order_by(BankTransaction.booked_on, BankTransaction.id).limit(limit + 1)

    rows = session.scalars(stmt).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1].booked_on, str(rows[-1].id)) if has_more else None
    return Page(items=[_to_out(t) for t in rows], next_cursor=next_cursor)


@router.patch("/transactions/{transaction_id}/category", response_model=TransactionOut)
def patch_category(
    transaction_id: uuid.UUID,
    body: TransactionCategoryPatch,
    session: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TransactionOut:
    txn = session.get(BankTransaction, transaction_id)
    if txn is None:
        raise AppError(404, "not_found", "Операция не найдена")
    _require_member(session, user.id, str(txn.company_id))
    # Ручная правка переопределяет авто-категорию и сохраняется (source=manual, confidence=1).
    txn.category = body.category
    txn.category_source = "manual"
    txn.category_confidence = 1.0
    txn.category_reason = "Исправлено пользователем"
    session.flush()
    return _to_out(txn)


def _require_member(session: Session, user_id: str, company_id: str) -> None:
    from app.core.models import CompanyMember

    if session.get(
        CompanyMember, {"company_id": uuid.UUID(company_id), "user_id": uuid.UUID(user_id)}
    ) is None:
        raise AppError(404, "not_found", "Операция не найдена")


def _to_out(t: BankTransaction) -> TransactionOut:
    return TransactionOut(
        id=str(t.id),
        account_id=str(t.account_id),
        booked_on=t.booked_on,
        amount_minor=t.amount_minor,
        direction=t.direction,
        currency=t.currency,
        counterparty_name=t.counterparty_name,
        purpose=t.purpose,
        category=t.category,
        category_source=t.category_source,
        category_confidence=t.category_confidence,
    )
