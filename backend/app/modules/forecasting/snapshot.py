"""Сборка снимка входных данных для прогноза из БД и его версия (data_version).

data_version — sha256 от детерминированно сериализованного входа. Один и тот же вход
даёт один и тот же хеш, поэтому уникальный ключ ForecastRun ловит повторный расчёт.
Начальный остаток берём из проверенного дневного остатка на дату среза (или ближайшего ранее).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import BankTransaction, DailyBalance, PlannedEvent
from app.modules.contracts import (
    DailyBalanceDTO,
    Direction,
    ForecastInput,
    PlannedEventDTO,
    ScenarioChange,
    TxnDTO,
)


@dataclass(frozen=True, slots=True)
class Snapshot:
    data: ForecastInput
    data_version: str
    opening_balance_minor: int
    warnings: list[str]


def build_snapshot(
    session: Session,
    *,
    account_id: str,
    as_of: date,
    horizon_days: int,
    seed: int,
    scenario: list[ScenarioChange] | None = None,
) -> Snapshot:
    warnings: list[str] = []

    txns = session.scalars(
        select(BankTransaction)
        .where(BankTransaction.account_id == account_id, BankTransaction.booked_on <= as_of)
        .order_by(BankTransaction.booked_on, BankTransaction.source_row)
    ).all()
    txn_dtos = [
        TxnDTO(
            id=str(t.id),
            account_id=str(t.account_id),
            booked_on=t.booked_on,
            amount_minor=t.amount_minor,
            direction=Direction(t.direction),
            currency=t.currency,
            counterparty_name=t.counterparty_name,
            counterparty_ref=t.counterparty_ref,
            purpose=t.purpose,
            category=t.category,
        )
        for t in txns
    ]

    balances = session.scalars(
        select(DailyBalance)
        .where(DailyBalance.account_id == account_id, DailyBalance.balance_date <= as_of)
        .order_by(DailyBalance.balance_date)
    ).all()
    balance_dtos = [
        DailyBalanceDTO(
            account_id=str(b.account_id),
            balance_date=b.balance_date,
            closing_balance_minor=b.closing_balance_minor,
        )
        for b in balances
    ]

    # Начальный остаток: проверенный остаток на дату среза или ближайший до неё.
    opening = next((b.closing_balance_minor for b in reversed(balances)), None)
    if opening is None:
        opening = 0
        warnings.append("Нет подтверждённого остатка на дату среза: начальный баланс принят за 0.")

    # Плановые события только те, что известны на дату среза (available_at <= as_of) —
    # для честного прогноза не подмешиваем будущее знание.
    events = session.scalars(
        select(PlannedEvent).where(
            PlannedEvent.account_id == account_id,
            PlannedEvent.due_date > as_of,
            PlannedEvent.status != "cancelled",
        )
    ).all()
    event_dtos = [
        PlannedEventDTO(
            id=str(e.id),
            direction=Direction(e.direction),
            amount_minor=e.amount_minor,
            remaining_amount_minor=e.remaining_amount_minor,
            due_date=e.due_date,
            status=e.status,
            kind=e.kind,
            source=e.source,
            available_at=e.available_at.date(),
            counterparty_ref=e.counterparty_name,
            recurrence_group=e.recurrence_group,
        )
        for e in events
        if e.available_at.date() <= as_of
    ]

    data = ForecastInput(
        account_id=str(account_id),
        as_of=as_of,
        horizon_days=horizon_days,
        opening_balance_minor=opening,
        seed=seed,
        txns=txn_dtos,
        daily_balances=balance_dtos,
        planned_events=event_dtos,
        scenario=scenario or [],
    )
    version = _version(txn_dtos, balance_dtos, event_dtos, as_of, horizon_days)
    return Snapshot(data=data, data_version=version, opening_balance_minor=opening, warnings=warnings)


def _version(txns, balances, events, as_of: date, horizon: int) -> str:
    payload = {
        "as_of": as_of.isoformat(),
        "horizon": horizon,
        "txns": [[t.id, t.amount_minor, t.direction.value, t.booked_on.isoformat()] for t in txns],
        "balances": [[b.balance_date.isoformat(), b.closing_balance_minor] for b in balances],
        "events": [[e.id, e.remaining_amount_minor, e.due_date.isoformat(), e.status] for e in events],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
