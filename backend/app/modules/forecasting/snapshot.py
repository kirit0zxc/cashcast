"""Сборка снимка входных данных для прогноза из БД и его версия (data_version).

data_version — sha256 от детерминированно сериализованного входа. Один и тот же вход
даёт один и тот же хеш, поэтому уникальный ключ ForecastRun ловит повторный расчёт.
Начальный остаток: последний EOD плюс известные потоки после него до даты среза.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.forecast_input import ForecastInputCodec
from app.core.models import Account, BankTransaction, DailyBalance, PlannedEvent
from app.core.snapshot_budget import SnapshotRowBudget
from app.modules.categorization.service import get_categorizer
from app.modules.contracts import (
    DailyBalanceDTO,
    Direction,
    ForecastInput,
    PlannedEventDTO,
    ScenarioChange,
    TxnDTO,
)
from app.modules.planning.service import get_recurrence_detector


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
    account = session.scalar(select(Account).where(Account.id == uuid.UUID(str(account_id))).with_for_update())
    if account is None:
        raise AppError(404, "not_found", "Счёт не найден")
    if account.currency != "RUB":
        raise AppError(422, "unsupported_currency", "Прогноз MVP поддерживает только RUB")
    budget = SnapshotRowBudget(session)
    budget.ensure_account(account_id, as_of)

    txns = session.scalars(
        select(BankTransaction)
        .where(BankTransaction.account_id == account_id, BankTransaction.booked_on <= as_of)
        .order_by(BankTransaction.booked_on, BankTransaction.id)
        .limit(budget.limits.transactions + 1)
    ).all()
    budget.ensure_count(len(txns), budget.limits.transactions)
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
    if any(t.currency != "RUB" for t in txn_dtos):
        raise AppError(422, "unsupported_currency", "MVP поддерживает только операции RUB одного счёта")
    assignments = {a.transaction_id: a for a in get_categorizer().categorize(txn_dtos)}
    txn_dtos = [replace(t, category=assignments[t.id].category.value)
                if t.category is None and t.id in assignments else t for t in txn_dtos]

    balances = session.scalars(
        select(DailyBalance)
        .where(DailyBalance.account_id == account_id, DailyBalance.balance_date <= as_of)
        .order_by(DailyBalance.balance_date)
        .limit(budget.limits.balances + 1)
    ).all()
    budget.ensure_count(len(balances), budget.limits.balances)
    balance_dtos = [
        DailyBalanceDTO(
            account_id=str(b.account_id),
            balance_date=b.balance_date,
            closing_balance_minor=b.closing_balance_minor,
        )
        for b in balances
    ]

    # EOD уже включает операции своего дня. Переносим только более поздние
    # известные факты; расчётный уровень не записывается как подтверждённый EOD.
    opening = next((b.closing_balance_minor for b in reversed(balances)), None)
    if opening is None:
        opening = 0
        warnings.append("Нет подтверждённого остатка на дату среза: начальный баланс принят за 0.")
    elif balances[-1].balance_date < as_of:
        warnings.append(f"Последний подтверждённый остаток: {balances[-1].balance_date}; "
                        "на дату среза остаток не подтверждён.")
        later = [t for t in txn_dtos if balances[-1].balance_date < t.booked_on <= as_of]
        if later:
            opening += sum(t.amount_minor if t.direction == Direction.IN else -t.amount_minor for t in later)
            warnings.append("Остаток на дату среза расчётный: к последнему EOD добавлены известные операции; "
                            "полнота последующей выписки не подтверждена.")

    # Плановые события только те, что известны на дату среза (available_at <= as_of) —
    # для честного прогноза не подмешиваем будущее знание.
    events = session.scalars(
        select(PlannedEvent).where(
            PlannedEvent.account_id == account_id,
            PlannedEvent.available_at <= datetime.combine(as_of, time.max, UTC),
        ).order_by(PlannedEvent.id).limit(budget.limits.events + 1)
    ).all()
    budget.ensure_count(len(events), budget.limits.events)
    # Paid/cancelled подавляют повтор регулярности, просроченные активные нужны модели.
    if any(e.currency != "RUB" and e.available_at.date() <= as_of for e in events):
        raise AppError(422, "unsupported_currency", "В планах счёта есть неподдерживаемая валюта")
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
            counterparty_ref=e.counterparty_ref or e.counterparty_name,
            recurrence_group=e.recurrence_group,
            category=e.category,
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
        recurrences=get_recurrence_detector().detect(txn_dtos, as_of),
    )
    # Полный вход, включая категории, контрагентов и регулярности, участвует в версии.
    payload = ForecastInputCodec.encode(data)["input"]
    for key in ("seed", "scenario", "data_version"):
        payload.pop(key)
    version = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    data = replace(data, data_version=version)
    return Snapshot(data=data, data_version=version, opening_balance_minor=opening, warnings=warnings)
