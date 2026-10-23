"""Сопоставление план/факт: предложения, без мутаций и записей в БД."""

from __future__ import annotations

from collections import Counter

from app.modules.categorization.service import normalize
from app.modules.contracts import MatchProposal, PlannedEventDTO, TxnDTO


class ConservativePlannedEventMatcher:
    def match(self, planned: list[PlannedEventDTO], txns: list[TxnDTO]) -> list[MatchProposal]:
        # В DTO нет account у события и нет as_of у match: границу счёта и срез
        # обеспечивает вызывающий сервис по согласованному wiring-v1.
        if len({txn.account_id for txn in txns}) > 1:
            raise ValueError("План-факт требует операции одного счёта")
        events = {event.id: event for event in planned}
        operations = {txn.id: txn for txn in txns}
        if len(events) != len(planned) or len(operations) != len(txns):
            raise ValueError("Повторные идентификаторы план-факта")
        edges = []
        for event in sorted(events.values(), key=lambda e: e.id):
            if event.status not in {"planned", "partially_paid"} or event.remaining_amount_minor <= 0:
                continue
            for txn in sorted(operations.values(), key=lambda t: t.id):
                if txn.currency != "RUB" or txn.direction != event.direction or txn.amount_minor <= 0:
                    continue
                if txn.booked_on < event.available_at or abs((txn.booked_on - event.due_date).days) > 7:
                    continue
                ref = normalize(event.counterparty_ref)
                txn_refs = {normalize(txn.counterparty_ref), normalize(txn.counterparty_name)} - {""}
                # Явное противоречие контрагента исключает даже кандидата.
                if ref and txn_refs and ref not in txn_refs:
                    continue
                identity = bool(ref and ref in txn_refs)
                # Без идентичности совпадение суммы/даты даёт только кандидата.
                if not identity and txn.amount_minor != event.remaining_amount_minor:
                    continue
                edges.append((event, txn, identity))
        event_degree = Counter(event.id for event, _, _ in edges)
        txn_degree = Counter(txn.id for _, txn, _ in edges)
        result = []
        for event, txn, identity in edges:
            unique = event_degree[event.id] == txn_degree[txn.id] == 1
            auto = identity and unique and txn.amount_minor <= event.remaining_amount_minor
            amount = min(txn.amount_minor, event.remaining_amount_minor)
            if auto:
                reason = "Единственное совпадение контрагента, направления и даты; полная или частичная оплата."
            else:
                reason = "Кандидат: неоднозначность, переплата или нет идентификатора; требуется подтверждение."
            result.append(MatchProposal(event.id, txn.id, amount, 0.9 if auto else 0.4, reason, auto))
        return result
