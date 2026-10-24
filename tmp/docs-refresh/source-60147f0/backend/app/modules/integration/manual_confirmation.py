"""Ручная сверка текущего предложения без обхода matcher и денежных остатков."""

import uuid
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.models import Account, BankTransaction, PlannedEvent, PlannedEventMatch
from app.modules.integration.plan_fact import PlanFactService


class ManualPlanFactConfirmation:
    def __init__(self, session: Session):
        self.session = session

    def confirm(self, company_id: uuid.UUID, account_id: uuid.UUID, event_id: uuid.UUID,
                transaction_id: uuid.UUID, amount: int) -> dict:
        today = datetime.now(UTC).date()
        cutoff = datetime.combine(today + timedelta(days=1), time.min, UTC)
        # Тот же account lock используют импорт, auto-reconcile и правки плана.
        account = self.session.scalar(select(Account).where(
            Account.id == account_id, Account.company_id == company_id,
        ).with_for_update())
        if account is None:
            raise AppError(404, "not_found", "Счёт не найден")
        event = self.session.scalar(select(PlannedEvent).where(
            PlannedEvent.id == event_id, PlannedEvent.company_id == company_id,
            PlannedEvent.account_id == account_id,
        ))
        txn = self.session.scalar(select(BankTransaction).where(
            BankTransaction.id == transaction_id, BankTransaction.company_id == company_id,
            BankTransaction.account_id == account_id,
        ))
        if event is None or txn is None:
            raise AppError(404, "not_found", "План или операция не найдены")
        existing = self.session.scalar(select(PlannedEventMatch).where(
            PlannedEventMatch.planned_event_id == event_id,
            PlannedEventMatch.transaction_id == transaction_id,
        ))
        service = PlanFactService(self.session)
        if existing is not None:
            if existing.status == "confirmed" and existing.matched_amount_minor == amount:
                # Повтор не меняет method, время или сумму прежде записанной связи.
                return {"as_of": today, **service.run(company_id, account_id, today)}
            raise AppError(409, "allocation_conflict", "Для этой пары уже сохранено другое решение")
        if (account.currency != "RUB" or event.currency != "RUB" or txn.currency != "RUB"
                or event.direction != txn.direction or event.available_at >= cutoff or txn.booked_on > today):
            raise AppError(409, "proposal_stale", "Предложение больше не доступно; обновите план-факт")
        data = service.run(company_id, account_id, today)
        proposal = next((p for p in data["proposals"]
                         if p.planned_event_id == str(event_id) and p.transaction_id == str(transaction_id)), None)
        if proposal is None:
            raise AppError(409, "proposal_stale", "Предложение больше не доступно; обновите план-факт")
        # Не только текущая страница/дата: все confirmed allocations расходуют бюджет.
        used_txn = self.session.scalar(select(func.coalesce(func.sum(PlannedEventMatch.matched_amount_minor), 0)).where(
            PlannedEventMatch.transaction_id == transaction_id, PlannedEventMatch.status == "confirmed",
        ))
        used_event = self.session.scalar(select(func.coalesce(
            func.sum(PlannedEventMatch.matched_amount_minor), 0,
        )).where(
            PlannedEventMatch.planned_event_id == event_id, PlannedEventMatch.status == "confirmed",
        ))
        if amount <= 0 or amount > min(proposal.matched_amount_minor, event.remaining_amount_minor,
                                       event.amount_minor - used_event, txn.amount_minor - used_txn):
            raise AppError(409, "allocation_conflict", "Изменился доступный остаток плана или операции")
        self.session.add(PlannedEventMatch(
            planned_event_id=event_id, transaction_id=transaction_id, matched_amount_minor=amount,
            status="confirmed", method="manual", confidence=proposal.confidence,
            reason="Подтверждено пользователем. " + proposal.reason,
        ))
        event.remaining_amount_minor -= amount
        event.status = "paid" if event.remaining_amount_minor == 0 else "partially_paid"
        self.session.flush()
        # Ответ и запись имеют одну транзакционную границу; get_db commit до HTTP200.
        return {"as_of": today, **service.run(company_id, account_id, today)}
