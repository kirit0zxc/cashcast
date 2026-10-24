"""Предел отдельных таблиц не ограничивает декартово произведение план-факт."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, insert, select

from app.core.models import BankTransaction, ForecastRun, Job, PlannedEvent, PlannedEventMatch
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


@pytest.mark.parametrize("action", ["get", "reconcile", "forecast", "confirm"])
def test_excessive_matching_product_rejected_before_matcher_and_writes(
    client, session_factory, context, monkeypatch, action,
):
    company, _, account, _ = context
    today = datetime.now(UTC).date()
    event_ids = [uuid.uuid4() for _ in range(200)]
    txn_ids = [uuid.uuid4() for _ in range(501)]
    common = {"company_id": uuid.UUID(company), "account_id": uuid.UUID(account)}
    with session_factory.begin() as db:
        db.execute(insert(PlannedEvent), [
            {**common, "id": identifier, "direction": "out", "amount_minor": 100,
             "remaining_amount_minor": 100, "due_date": today, "counterparty_ref": "same-party"}
            for identifier in event_ids
        ])
        db.execute(insert(BankTransaction), [
            {**common, "id": identifier, "direction": "out", "amount_minor": 100,
             "booked_on": today, "counterparty_ref": "same-party", "fingerprint": str(identifier)}
            for identifier in txn_ids
        ])

    class UnreachableMatcher:
        def match(self, *_args):
            raise AssertionError("Превышенный matching budget дошёл до декартова произведения")

    monkeypatch.setattr("app.modules.integration.plan_fact.get_planned_event_matcher", UnreachableMatcher)
    params = {"account_id": account, "as_of": today.isoformat()}
    path = f"/api/v1/companies/{company}"
    if action == "get":
        response = client.get(path + "/plan-fact", params=params)
    elif action == "reconcile":
        response = client.post(path + "/plan-fact", params=params)
    elif action == "forecast":
        response = client.post(path + "/forecasts", json={**params, "horizon_days": 30})
    else:
        response = client.post(path + "/plan-fact/confirm", json={
            "account_id": account, "planned_event_id": str(event_ids[0]),
            "transaction_id": str(txn_ids[0]), "matched_amount_minor": 100,
        })
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "plan_fact_resource_limit"
    with session_factory() as db:
        for table in (Job, ForecastRun, PlannedEventMatch):
            assert db.scalar(select(func.count()).select_from(table)) == 0
        assert set(db.scalars(select(PlannedEvent.remaining_amount_minor))) == {100}


def test_matching_budget_boundary_is_explicit_and_closed_plans_do_not_count():
    from app.core.snapshot_budget import SnapshotRowBudget

    SnapshotRowBudget.ensure_matching(200, 500)
    SnapshotRowBudget.ensure_matching(0, 50_000)
    from app.core.errors import AppError

    with pytest.raises(AppError) as error:
        SnapshotRowBudget.ensure_matching(200, 501)
    assert error.value.code == "plan_fact_resource_limit"
