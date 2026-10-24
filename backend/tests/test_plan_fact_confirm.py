"""Ручной выбор не обходит matcher, tenant isolation и два денежных бюджета."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.models import BankTransaction, PlannedEvent, PlannedEventMatch
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _source(session_factory, context, *, plans=1, amount=10000, txn_amount=10000):
    company, _, account, _ = context
    today = datetime.now(UTC).date()
    with session_factory.begin() as session:
        events = [PlannedEvent(
            company_id=uuid.UUID(company), account_id=uuid.UUID(account), direction="out",
            amount_minor=amount, remaining_amount_minor=amount, due_date=today,
            counterparty_name="Поставщик", source="manual", kind="manual", status="planned",
        ) for _ in range(plans)]
        txn = BankTransaction(
            company_id=uuid.UUID(company), account_id=uuid.UUID(account), booked_on=today,
            direction="out", amount_minor=txn_amount, fingerprint=f"confirm-{uuid.uuid4()}",
            counterparty_name="Поставщик", purpose="Синтетическая проверка", currency="RUB",
        )
        session.add_all([*events, txn])
        session.flush()
        return [str(e.id) for e in events], str(txn.id)


def _body(context, event_id, transaction_id, amount=10000):
    return {"account_id": context[2], "planned_event_id": event_id,
            "transaction_id": transaction_id, "matched_amount_minor": amount}


def _post(client, context, body):
    return client.post(f"/api/v1/companies/{context[0]}/plan-fact/confirm", json=body)


def _assert_stored(session_factory, event_id, amount, remaining):
    with session_factory() as session:
        event = session.get(PlannedEvent, event_id)
        assert event.remaining_amount_minor == remaining
        assert session.scalar(select(func.coalesce(func.sum(PlannedEventMatch.matched_amount_minor), 0))) == amount


def test_manual_partial_confirm_repeated_amount_is_idempotent_and_different_amount_conflicts(
    client, context, session_factory,
):
    events, txn = _source(session_factory, context)
    body = _body(context, events[0], txn, 4000)
    for _ in range(2):
        response = _post(client, context, body)
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["confirmed_amount_minor"] == 4000
        assert item["event"]["remaining_amount_minor"] == 6000
        assert item["event"]["status"] == "partially_paid"
        assert len(response.json()["confirmed_matches"]) == 1
    different = _post(client, context, {**body, "matched_amount_minor": 6000})
    assert different.status_code == 409 and different.json()["error"]["code"] == "allocation_conflict"
    _assert_stored(session_factory, events[0], 4000, 6000)
    with session_factory() as session:
        link = session.scalar(select(PlannedEventMatch))
        assert link.status == "confirmed" and link.method == "manual"


def test_manual_confirmation_rejects_over_proposal_amount_without_writes(client, context, session_factory):
    events, txn = _source(session_factory, context, amount=15000, txn_amount=10000)
    response = _post(client, context, _body(context, events[0], txn, 10001))
    assert response.status_code == 409 and response.json()["error"]["code"] == "allocation_conflict"
    _assert_stored(session_factory, events[0], 0, 15000)


@pytest.mark.parametrize("value", [0, -1, 9000000000000001, True, "10000", 10000.0])
def test_manual_confirmation_requires_strict_positive_bounded_minor_integer(client, context, session_factory, value):
    events, txn = _source(session_factory, context)
    response = _post(client, context, _body(context, events[0], txn, value))
    assert response.status_code == 422, response.text
    _assert_stored(session_factory, events[0], 0, 10000)


@pytest.mark.parametrize("field", ["as_of", "extra"])
def test_manual_confirmation_forbids_unapproved_body_fields(client, context, session_factory, field):
    events, txn = _source(session_factory, context)
    response = _post(client, context, {**_body(context, events[0], txn), field: "2024-01-01"})
    assert response.status_code == 422
    _assert_stored(session_factory, events[0], 0, 10000)


def test_manual_confirmation_requires_session_csrf_and_owned_company_account_objects(client, context, session_factory):
    events, txn = _source(session_factory, context)
    body = _body(context, events[0], txn)
    assert client.post(f"/api/v1/companies/{context[1]}/plan-fact/confirm", json=body).status_code == 404
    for field in ("account_id", "planned_event_id", "transaction_id"):
        assert _post(client, context, {**body, field: str(uuid.uuid4())}).status_code == 404
        assert _post(client, context, {**body, field: "not-uuid"}).status_code == 422
    assert _post(client, context, {**body, "account_id": context[3]}).status_code == 404
    # Подмена фактических объектов другим счётом той же компании тоже запрещена.
    other_events, other_txn = _source(session_factory, (context[0], context[1], context[3], context[2]))
    assert _post(client, context, {**body, "planned_event_id": other_events[0]}).status_code == 404
    assert _post(client, context, {**body, "transaction_id": other_txn}).status_code == 404
    csrf = client.headers.pop("X-CSRF-Token")
    assert _post(client, context, body).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    client.cookies.clear()
    assert _post(client, context, body).status_code == 401
    _assert_stored(session_factory, events[0], 0, 10000)


@pytest.mark.parametrize("change", ["cancelled", "future_plan", "future_txn", "direction", "currency", "counterparty"])
def test_changed_or_ineligible_pair_is_stale_and_not_confirmed(client, context, session_factory, change):
    events, txn = _source(session_factory, context)
    with session_factory.begin() as session:
        event, operation = session.get(PlannedEvent, events[0]), session.get(BankTransaction, txn)
        if change == "cancelled":
            event.status = "cancelled"
        elif change == "future_plan":
            event.available_at = datetime.now(UTC) + timedelta(days=2)
        elif change == "future_txn":
            operation.booked_on += timedelta(days=2)
        elif change == "direction":
            operation.direction = "in"
        elif change == "currency":
            operation.currency = "USD"
        else:
            operation.counterparty_name = "Другая компания"
    response = _post(client, context, _body(context, events[0], txn))
    assert response.status_code == 409 and response.json()["error"]["code"] == "proposal_stale", response.text
    _assert_stored(session_factory, events[0], 0, 10000)


def test_all_confirmed_links_even_future_dated_consume_transaction_budget(client, context, session_factory):
    events, txn = _source(session_factory, context, plans=2)
    with session_factory.begin() as session:
        session.add(PlannedEventMatch(
            planned_event_id=uuid.UUID(events[0]), transaction_id=uuid.UUID(txn), matched_amount_minor=10000,
            status="confirmed", method="manual", created_at=datetime.now(UTC) + timedelta(days=2),
        ))
        session.get(PlannedEvent, events[0]).remaining_amount_minor = 0
        session.get(PlannedEvent, events[0]).status = "paid"
    response = _post(client, context, _body(context, events[1], txn))
    assert response.status_code == 409 and response.json()["error"]["code"] == "allocation_conflict"
    _assert_stored(session_factory, events[1], 10000, 10000)


def _parallel_request(client, path, body):
    tab = TestClient(client.app, raise_server_exceptions=False)
    tab.cookies.update(client.cookies)
    tab.headers["X-CSRF-Token"] = client.headers["X-CSRF-Token"]
    return tab.post(path, json=body)


def test_two_ambiguous_choices_cannot_consume_one_transaction_twice(client, context, session_factory):
    events, txn = _source(session_factory, context, plans=2)
    path = f"/api/v1/companies/{context[0]}/plan-fact/confirm"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda event: _parallel_request(client, path, _body(context, event, txn)), events))
    assert sorted(response.status_code for response in responses) == [200, 409], [r.text for r in responses]
    failed = next(r for r in responses if r.status_code == 409)
    assert failed.json()["error"]["code"] == "proposal_stale"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEventMatch)) == 1
        assert session.scalar(select(func.sum(PlannedEvent.remaining_amount_minor))) == 10000


def test_same_pair_parallel_retries_return_one_confirmed_link(client, context, session_factory):
    events, txn = _source(session_factory, context)
    path = f"/api/v1/companies/{context[0]}/plan-fact/confirm"
    body = _body(context, events[0], txn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: _parallel_request(client, path, body), range(2)))
    assert [response.status_code for response in responses] == [200, 200], [r.text for r in responses]
    _assert_stored(session_factory, events[0], 10000, 0)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEventMatch)) == 1


def test_confirmation_rolls_back_if_response_assembly_fails(client, context, session_factory, monkeypatch):
    from app.core.errors import AppError
    from app.modules.integration.plan_fact import PlanFactService

    events, txn = _source(session_factory, context)
    original = PlanFactService.run
    calls = 0

    def fail_after_write(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AppError(409, "test_response_failure", "Синтетический отказ до commit")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PlanFactService, "run", fail_after_write)
    response = _post(client, context, _body(context, events[0], txn))
    assert response.status_code == 409 and response.json()["error"]["code"] == "test_response_failure"
    _assert_stored(session_factory, events[0], 0, 10000)


def test_previous_partial_allocation_limits_new_pair_and_preserves_saved_forecast(client, context, session_factory):
    from app.core.models import ForecastRun

    events, txn = _source(session_factory, context, plans=2)
    first = _post(client, context, _body(context, events[0], txn, 4000))
    assert first.status_code == 200, first.text
    with session_factory.begin() as session:
        run = ForecastRun(company_id=uuid.UUID(context[0]), account_id=uuid.UUID(context[2]),
                          as_of=datetime.now(UTC).date(), horizon_days=30, data_version="frozen-confirm",
                          model_version="baseline-0.1.0", seed=42, status="succeeded",
                          input_snapshot={"unchanged": "input"}, details={"unchanged": "result"})
        session.add(run)
        session.flush()
        run_id = run.id
    conflict = _post(client, context, _body(context, events[1], txn, 6001))
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "allocation_conflict"
    response = _post(client, context, _body(context, events[1], txn, 6000))
    assert response.status_code == 200, response.text
    assert not response.json()["proposals"]
    _assert_stored(session_factory, events[1], 10000, 4000)
    with session_factory() as session:
        run = session.get(ForecastRun, run_id)
        assert run.input_snapshot == {"unchanged": "input"} and run.details == {"unchanged": "result"}


@pytest.mark.parametrize("status", ["candidate", "rejected"])
def test_legacy_nonconfirmed_decision_is_not_overwritten_silently(client, context, session_factory, status):
    events, txn = _source(session_factory, context)
    with session_factory.begin() as session:
        session.add(PlannedEventMatch(
            planned_event_id=uuid.UUID(events[0]), transaction_id=uuid.UUID(txn), matched_amount_minor=10000,
            status=status, method="manual", reason="Прежнее решение",
        ))
    response = _post(client, context, _body(context, events[0], txn))
    assert response.status_code == 409 and response.json()["error"]["code"] == "allocation_conflict"
    with session_factory() as session:
        assert session.get(PlannedEvent, events[0]).remaining_amount_minor == 10000
        link = session.scalar(select(PlannedEventMatch))
        assert link.status == status and link.reason == "Прежнее решение"


def test_manual_confirm_and_auto_reconcile_serialize_without_changing_recorded_method(client, context, session_factory):
    events, txn = _source(session_factory, context)
    path = f"/api/v1/companies/{context[0]}/plan-fact"

    def auto():
        tab = TestClient(client.app, raise_server_exceptions=False)
        tab.cookies.update(client.cookies)
        tab.headers["X-CSRF-Token"] = client.headers["X-CSRF-Token"]
        return tab.post(path, params={"account_id": context[2], "as_of": datetime.now(UTC).date().isoformat()})

    with ThreadPoolExecutor(max_workers=2) as pool:
        manual = pool.submit(_parallel_request, client, path + "/confirm", _body(context, events[0], txn))
        automatic = pool.submit(auto)
        responses = [manual.result(timeout=15), automatic.result(timeout=15)]
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    _assert_stored(session_factory, events[0], 10000, 0)
    with session_factory() as session:
        previous = session.scalar(select(PlannedEventMatch))
        state = previous.id, previous.method, previous.created_at, previous.reason
    assert _post(client, context, _body(context, events[0], txn)).status_code == 200
    with session_factory() as session:
        previous = session.scalar(select(PlannedEventMatch))
        assert (previous.id, previous.method, previous.created_at, previous.reason) == state
