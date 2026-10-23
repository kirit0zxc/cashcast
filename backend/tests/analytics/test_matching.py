"""Полные, частичные и неоднозначные совпадения."""

from dataclasses import replace
from datetime import date

import pytest

from app.modules.contracts import Direction, PlannedEventDTO, TxnDTO
from app.modules.planning.matching import ConservativePlannedEventMatcher


def event(**kwargs):
    return replace(
        PlannedEventDTO(
            "ev",
            Direction.OUT,
            10000,
            10000,
            date(2026, 1, 10),
            "planned",
            "invoice",
            "manual",
            date(2026, 1, 1),
            "0012345678",
        ),
        **kwargs,
    )


def txn(**kwargs):
    return replace(
        TxnDTO("tx", "acc", date(2026, 1, 10), 10000, Direction.OUT, counterparty_ref="0012345678"), **kwargs
    )


@pytest.mark.parametrize("amount", [10000, 4000])
def test_unique_full_or_partial_payment(amount):
    proposal = ConservativePlannedEventMatcher().match([event()], [txn(amount_minor=amount)])[0]
    assert proposal.auto_confirm
    assert proposal.matched_amount_minor == amount


def test_paid_cancelled_future_unknown_opposite_and_currency_do_not_match():
    service = ConservativePlannedEventMatcher()
    for ev in [
        event(status="paid"),
        event(status="cancelled"),
        event(remaining_amount_minor=0),
        event(available_at=date(2026, 1, 11)),
    ]:
        assert service.match([ev], [txn()]) == []
    for tx in [
        txn(direction=Direction.IN),
        txn(currency="USD"),
        txn(counterparty_ref="0099999999"),
        txn(booked_on=date(2026, 2, 1)),
    ]:
        assert service.match([event()], [tx]) == []


def test_ambiguity_is_never_confirmed_or_mutated():
    events = [event(), event(id="ev2")]
    operations = [txn(), txn(id="tx2")]
    proposals = ConservativePlannedEventMatcher().match(events, operations)
    assert len(proposals) == 4
    assert not any(p.auto_confirm for p in proposals)
    assert all(ev.remaining_amount_minor == 10000 for ev in events)
    assert proposals == ConservativePlannedEventMatcher().match(list(reversed(events)), list(reversed(operations)))


def test_overpayment_and_missing_identity_are_candidates():
    service = ConservativePlannedEventMatcher()
    assert not service.match([event()], [txn(amount_minor=20000)])[0].auto_confirm
    assert not service.match([event(counterparty_ref=None)], [txn()])[0].auto_confirm


def test_mixed_accounts_and_duplicate_ids_rejected():
    service = ConservativePlannedEventMatcher()
    with pytest.raises(ValueError):
        service.match([event()], [txn(), txn(id="tx2", account_id="other")])
    with pytest.raises(ValueError):
        service.match([event(), event()], [txn()])
