"""Плановые события: список, создание, правка даты/суммы/отмены."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.models import PlannedEventIn, PlannedEventOut, PlannedEventPatch
from app.core.auth import CurrentUser, get_current_user, require_company_access
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import Account, PlannedEvent
from app.core.plan_capacity import PlanCapacityPolicy

router = APIRouter(tags=["planned-events"], responses=ERROR_RESPONSES)


@router.get("/companies/{company_id}/planned-events", response_model=list[PlannedEventOut])
def list_events(
    company_id: uuid.UUID,
    _company: str = Depends(require_company_access),
    session: Session = Depends(get_db, scope="function"),
) -> list[PlannedEventOut]:
    rows = session.scalars(
        select(PlannedEvent)
        .where(PlannedEvent.company_id == company_id)
        .order_by(PlannedEvent.due_date)
    ).all()
    return [_to_out(e) for e in rows]


@router.post("/companies/{company_id}/planned-events", response_model=PlannedEventOut, status_code=201)
def create_event(
    company_id: uuid.UUID,
    body: PlannedEventIn,
    _company: str = Depends(require_company_access),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> PlannedEventOut:
    if body.currency != "RUB":
        raise AppError(422, "unsupported_currency", "Плановые события MVP поддерживают только RUB")
    if body.account_id:
        acc = session.scalar(select(Account).where(Account.id == body.account_id).with_for_update())
        if acc is None or str(acc.company_id) != str(company_id):
            raise AppError(404, "not_found", "Счёт не найден")
        if acc.currency != body.currency:
            raise AppError(422, "currency_mismatch", "Валюта события должна совпадать с валютой счёта")
        PlanCapacityPolicy(session).ensure_change(acc.id, added_count=1, remaining_delta=body.amount_minor)
    event = PlannedEvent(
        company_id=company_id,
        account_id=body.account_id,
        direction=body.direction,
        amount_minor=body.amount_minor,
        remaining_amount_minor=body.amount_minor,
        currency=body.currency,
        due_date=body.due_date,
        kind=body.kind,
        source="manual",
        source_ref=body.source_ref,
        counterparty_name=body.counterparty_name,
        description=body.description,
        category=body.category,
        created_by=uuid.UUID(user.id),
    )
    session.add(event)
    session.flush()
    return _to_out(event)


@router.patch("/planned-events/{event_id}", response_model=PlannedEventOut)
def patch_event(
    event_id: uuid.UUID,
    body: PlannedEventPatch,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> PlannedEventOut:
    event = session.get(PlannedEvent, event_id)
    if event is None:
        raise AppError(404, "not_found", "Плановое событие не найдено")
    _require_member(session, user.id, str(event.company_id))
    if event.account_id is not None:
        # Общая с reconcile блокировка: изменение суммы не обгоняет подтверждение оплаты.
        session.scalar(select(Account).where(Account.id == event.account_id).with_for_update())
        session.refresh(event)

    previous_remaining = event.remaining_amount_minor

    if event.status in {"paid", "cancelled"} and (
        (body.amount_minor is not None and body.amount_minor != event.amount_minor)
        or (body.status is not None and body.status != event.status)
    ):
        # Нулевой остаток отмены не доказывает оплату. Без истории переходов
        # нельзя восстановить долг либо изменить закрытую сумму; exact repeat допустим.
        raise AppError(409, "closed_plan_event", "Закрытый план нельзя возобновить или изменить его сумму")

    if body.due_date is not None:
        event.due_date = body.due_date
    if body.amount_minor is not None:
        # Сохраняем уже оплаченную сумму, а не долю исходного обязательства.
        paid = event.amount_minor - event.remaining_amount_minor
        if body.amount_minor < paid:
            raise AppError(422, "amount_below_paid", "Сумма не может быть меньше уже оплаченной части")
        event.amount_minor = body.amount_minor
        event.remaining_amount_minor = max(0, body.amount_minor - paid)
        if event.status in {"planned", "partially_paid"}:
            event.status = "paid" if event.remaining_amount_minor == 0 else (
                "partially_paid" if paid else "planned"
            )
    if body.status is not None:
        event.status = body.status
        if body.status in {"cancelled", "paid"}:
            event.remaining_amount_minor = 0
    if event.status in {"planned", "partially_paid"}:
        expected = "paid" if event.remaining_amount_minor == 0 else (
            "planned" if event.remaining_amount_minor == event.amount_minor else "partially_paid"
        )
        if body.status is not None and body.status != expected:
            raise AppError(422, "invalid_plan_status", "Статус должен соответствовать оплаченной сумме")
        event.status = expected
    if event.account_id is not None:
        PlanCapacityPolicy(session).ensure_change(
            event.account_id, added_count=0, remaining_delta=event.remaining_amount_minor - previous_remaining,
        )
    session.flush()
    return _to_out(event)


def _require_member(session: Session, user_id: str, company_id: str) -> None:
    from app.core.models import CompanyMember

    if session.get(
        CompanyMember, {"company_id": uuid.UUID(company_id), "user_id": uuid.UUID(user_id)}
    ) is None:
        raise AppError(404, "not_found", "Плановое событие не найдено")


def _to_out(e: PlannedEvent) -> PlannedEventOut:
    return PlannedEventOut(
        id=str(e.id),
        account_id=str(e.account_id) if e.account_id else None,
        direction=e.direction,
        amount_minor=e.amount_minor,
        remaining_amount_minor=e.remaining_amount_minor,
        currency=e.currency,
        due_date=e.due_date,
        status=e.status,
        kind=e.kind,
        source=e.source,
        source_ref=e.source_ref,
        available_at=e.available_at,
        counterparty_name=e.counterparty_name,
        counterparty_ref=e.counterparty_ref,
        provenance=e.provenance,
        tax_regime=e.tax_regime,
        category=e.category,
    )
