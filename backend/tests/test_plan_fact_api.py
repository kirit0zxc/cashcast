"""Проверка атомарных аллокаций и состава входа прогноза, а не только чистого matcher."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.models import PlannedEvent, PlannedEventMatch
from app.modules.forecasting.snapshot import build_snapshot
from app.modules.integration.plan_fact import PlanFactService
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _event(client, company, account, amount, today):
    response = client.post(f"/api/v1/companies/{company}/planned-events", json={
        "account_id": account, "amount_minor": amount, "direction": "out", "due_date": today,
        "counterparty_name": "Поставщик",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _payment(client, company, account, amount, operation_id, today):
    mapping = client.get("/api/v1/import-presets").json()["items"][0]["mapping"]
    csv = ("operation_id;operation_date;amount;direction;counterparty_name;counterparty_inn;balance_eod\n"
           f"{operation_id};{today};{amount};Списание;Поставщик;00123;900.00\n")
    response = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps(mapping),
    }, files={"file": ("payment.csv", csv.encode("utf-8-sig"), "text/csv")})
    assert response.status_code == 200, response.text
    assert client.post(f"/api/v1/imports/{response.json()['import_id']}/commit").status_code == 200


def test_partial_payment_repeated_reconcile_and_consumed_transaction(client, session_factory, context):
    company, other, account, _ = context
    today = datetime.now(UTC).date().isoformat()
    event = _event(client, company, account, 15000, today)
    _payment(client, company, account, "100.00", "p1", today)
    path = f"/api/v1/companies/{company}/plan-fact"
    params = {"account_id": account, "as_of": today}
    preview = client.get(path, params=params).json()
    assert len(preview["proposals"]) == 1
    assert preview["items"][0]["event"]["remaining_amount_minor"] == 15000
    assert not preview["confirmed_matches"]
    for _ in range(2):
        response = client.post(path, params=params)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["items"][0]["event"]["remaining_amount_minor"] == 5000
        assert len(result["confirmed_matches"]) == 1
    assert client.patch(f"/api/v1/planned-events/{event}", json={"amount_minor": 5000}).status_code == 422
    _payment(client, company, account, "50.00", "p2", today)
    result = client.post(path, params=params).json()
    assert result["items"][0]["event"]["status"] == "paid"
    assert result["items"][0]["confirmed_amount_minor"] == 15000
    second = _event(client, company, account, 10000, today)
    result = client.post(path, params=params).json()
    by_id = {i["event"]["id"]: i for i in result["items"]}
    assert by_id[event]["event"]["remaining_amount_minor"] == 0
    assert by_id[second]["event"]["remaining_amount_minor"] == 10000
    assert sum(m["matched_amount_minor"] for m in result["confirmed_matches"]) == 15000
    assert not result["proposals"]
    assert client.get(f"/api/v1/companies/{other}/plan-fact", params=params).status_code == 404
    past = {**params, "as_of": (datetime.now(UTC).date() - timedelta(days=1)).isoformat()}
    assert client.post(path, params=past).status_code == 409
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEventMatch)) == 2


def test_concurrent_reconcile_cannot_allocate_the_same_payment_twice(client, session_factory, context):
    company, _, account, _ = context
    today = datetime.now(UTC).date()
    _event(client, company, account, 10000, today.isoformat())
    _payment(client, company, account, "100.00", "parallel", today.isoformat())

    def reconcile_once(_):
        with session_factory.begin() as session:
            return len(PlanFactService(session).run(uuid.UUID(company), uuid.UUID(account), today,
                                                   write=True)["links"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(reconcile_once, range(2))) == [1, 1]
    with session_factory() as session:
        assert session.scalar(select(func.sum(PlannedEventMatch.matched_amount_minor))) == 10000


def test_snapshot_keeps_known_closed_and_overdue_events_but_excludes_future_knowledge(session_factory, context):
    company, _, account, _ = context
    as_of = datetime.now(UTC).date() - timedelta(days=2)
    known = datetime.combine(as_of - timedelta(days=1), datetime.min.time(), UTC)
    with session_factory.begin() as session:
        for status, delta, available in [("cancelled", 5, known), ("paid", 6, known),
                                         ("planned", -1, known), ("planned", 8, datetime.now(UTC))]:
            session.add(PlannedEvent(
                company_id=uuid.UUID(company), account_id=uuid.UUID(account), direction="out",
                amount_minor=1000, remaining_amount_minor=1000 if status == "planned" else 0,
                due_date=as_of + timedelta(days=delta), status=status, kind="manual", source="manual",
                available_at=available, updated_at=available,
            ))
    with session_factory() as session:
        data = build_snapshot(session, account_id=account, as_of=as_of, horizon_days=30, seed=42).data
        assert len(data.planned_events) == 3
        assert {e.status for e in data.planned_events} == {"cancelled", "paid", "planned"}
        assert any(e.due_date < as_of for e in data.planned_events)


def test_foreign_currency_event_is_rejected_and_legacy_row_cannot_become_rubles(client, session_factory, context):
    company, _, account, _ = context
    today = datetime.now(UTC).date()
    response = client.post(f"/api/v1/companies/{company}/planned-events", json={
        "account_id": account, "amount_minor": 10000, "currency": "USD",
        "direction": "out", "due_date": today.isoformat(),
    })
    assert response.status_code == 422
    with session_factory.begin() as session:
        session.add(PlannedEvent(
            company_id=uuid.UUID(company), account_id=uuid.UUID(account), currency="USD",
            amount_minor=10000, remaining_amount_minor=10000, direction="out",
            due_date=today + timedelta(days=1), status="planned", kind="manual", source="manual",
        ))
    with session_factory() as session:
        with pytest.raises(AppError) as error:
            build_snapshot(session, account_id=account, as_of=today, horizon_days=30, seed=42)
        assert error.value.code == "unsupported_currency"
