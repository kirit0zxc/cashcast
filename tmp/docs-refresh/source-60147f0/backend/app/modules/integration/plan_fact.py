"""Аллокации факта: остатки операций, блокировка счёта и идемпотентность записи."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.models import Account, BankTransaction, PlannedEvent, PlannedEventMatch
from app.core.snapshot_budget import SnapshotRowBudget
from app.modules.contracts import Direction, PlannedEventDTO, TxnDTO
from app.modules.planning.service import get_planned_event_matcher


class PlanFactService:
    def __init__(self, session: Session):
        self.session = session

    def run(self, company_id: uuid.UUID, account_id: uuid.UUID, as_of: date, *, write: bool = False) -> dict:
        today = datetime.now(UTC).date()
        if as_of > today:
            raise AppError(422, "future_as_of", "Дата среза не может быть позже сегодняшнего дня UTC")
        if write and as_of != today:
            # Без версионной истории нельзя записать сегодняшнее решение как знание прошлого.
            raise AppError(409, "historical_reconcile_read_only", "Исторический план-факт доступен только для чтения")
        # GET держит shared lock, чтобы импорт/сверка не изменили источник между
        # чтениями планов и allocations. Несколько читателей друг другу не мешают.
        statement = select(Account).where(
            Account.id == account_id, Account.company_id == company_id,
        ).with_for_update(read=not write)
        account = self.session.scalar(statement)
        if account is None:
            raise AppError(404, "not_found", "Счёт не найден")
        if account.currency != "RUB":
            raise AppError(422, "unsupported_currency", "План-факт MVP поддерживает только RUB")
        budget = SnapshotRowBudget(self.session)
        budget.ensure_account(account_id, as_of, include_balances=False)
        cutoff = datetime.combine(as_of + timedelta(days=1), time.min, UTC)
        events = self.session.scalars(select(PlannedEvent).where(
            PlannedEvent.account_id == account_id, PlannedEvent.available_at < cutoff,
        ).order_by(PlannedEvent.id).limit(budget.limits.events + 1)).all()
        budget.ensure_count(len(events), budget.limits.events)
        if any(e.updated_at >= cutoff for e in events):
            raise AppError(409, "historical_plan_unavailable",
                           "Планы менялись после среза; история их версий пока не сохраняется")
        txns = self.session.scalars(select(BankTransaction).where(
            BankTransaction.account_id == account_id, BankTransaction.booked_on <= as_of,
        ).order_by(BankTransaction.id).limit(budget.limits.transactions + 1)).all()
        budget.ensure_count(len(txns), budget.limits.transactions)
        links = self.session.scalars(select(PlannedEventMatch).join(
            PlannedEvent, PlannedEvent.id == PlannedEventMatch.planned_event_id,
        ).join(BankTransaction, BankTransaction.id == PlannedEventMatch.transaction_id).where(
            PlannedEvent.account_id == account_id, BankTransaction.account_id == account_id,
            PlannedEventMatch.status == "confirmed", PlannedEventMatch.created_at < cutoff,
            BankTransaction.booked_on <= as_of, PlannedEvent.available_at < cutoff,
        )).all()
        used = {}
        confirmed = {}
        pairs = set()
        for link in links:
            tid, eid = str(link.transaction_id), str(link.planned_event_id)
            used[tid] = used.get(tid, 0) + link.matched_amount_minor
            confirmed[eid] = confirmed.get(eid, 0) + link.matched_amount_minor
            pairs.add((eid, tid))
        inputs = [TxnDTO(
            id=str(t.id), account_id=str(t.account_id), booked_on=t.booked_on,
            amount_minor=max(0, t.amount_minor - used.get(str(t.id), 0)), direction=Direction(t.direction),
            currency=t.currency, counterparty_name=t.counterparty_name, counterparty_ref=t.counterparty_ref,
            purpose=t.purpose, category=t.category,
        ) for t in txns if t.currency == "RUB" and t.amount_minor > used.get(str(t.id), 0)]
        plans = [PlannedEventDTO(
            id=str(e.id), direction=Direction(e.direction), amount_minor=e.amount_minor,
            remaining_amount_minor=e.remaining_amount_minor, due_date=e.due_date,
            status=e.status, kind=e.kind, source=e.source, available_at=e.available_at.date(),
            counterparty_ref=e.counterparty_ref or e.counterparty_name, recurrence_group=e.recurrence_group,
        ) for e in events if e.currency == "RUB"]
        active_count = sum(p.status in {"planned", "partially_paid"} and p.remaining_amount_minor > 0 for p in plans)
        budget.ensure_matching(active_count, len(inputs))
        proposals = [p for p in get_planned_event_matcher().match(plans, inputs)
                     if (p.planned_event_id, p.transaction_id) not in pairs]
        if write:
            by_id = {str(e.id): e for e in events}
            for proposal in proposals:
                if not proposal.auto_confirm:
                    continue
                # Старое candidate/rejected-решение не расходует сумму, но занимает
                # пару. Под общей блокировкой счёта сохраняем его, как ручная сверка.
                existing = self.session.scalar(select(PlannedEventMatch.id).where(
                    PlannedEventMatch.planned_event_id == uuid.UUID(proposal.planned_event_id),
                    PlannedEventMatch.transaction_id == uuid.UUID(proposal.transaction_id),
                ))
                if existing is not None:
                    raise AppError(409, "allocation_conflict", "Для этой пары уже сохранено другое решение")
                event = by_id[proposal.planned_event_id]
                # Чистый matcher гарантирует единственность; повторно проверяем бюджет на границе БД.
                remaining_txn = next(t.amount_minor for t in inputs if t.id == proposal.transaction_id)
                amount = proposal.matched_amount_minor
                if amount <= 0 or amount > min(event.remaining_amount_minor, remaining_txn):
                    raise AppError(409, "allocation_conflict", "Изменился доступный остаток операции")
                self.session.add(PlannedEventMatch(
                    planned_event_id=uuid.UUID(proposal.planned_event_id),
                    transaction_id=uuid.UUID(proposal.transaction_id), matched_amount_minor=amount,
                    status="confirmed", method="auto", confidence=proposal.confidence, reason=proposal.reason,
                ))
                event.remaining_amount_minor -= amount
                event.status = "paid" if event.remaining_amount_minor == 0 else "partially_paid"
            self.session.flush()
            return self.run(company_id, account_id, as_of)
        return {"events": events, "confirmed": confirmed, "links": links, "proposals": proposals}
