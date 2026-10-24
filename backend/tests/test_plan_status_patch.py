"""Правка плана не создаёт paid с остатком и не возрождает закрытый документ."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.test_accounts import account_context
from tests.test_plan_fact_api import _event, _payment


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


@pytest.mark.parametrize("status", ["paid", "cancelled"])
@pytest.mark.parametrize("patch", [{"amount_minor": 15000}, {"status": "planned"}, {"status": "partially_paid"}])
def test_terminal_plan_cannot_change_amount_or_reopen(client, context, status, patch):
    company, _, account, _ = context
    today = datetime.now(UTC).date()
    event = _event(client, company, account, 10000, today.isoformat())
    path = f"/api/v1/planned-events/{event}"
    closed = client.patch(path, json={"status": status})
    assert closed.status_code == 200
    before = closed.json()
    response = client.patch(path, json={**patch, "due_date": (today + timedelta(days=1)).isoformat()})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "closed_plan_event"
    stored = client.get(f"/api/v1/companies/{company}/planned-events").json()[0]
    assert stored == before, "Отказ не должен сохранить даже новую дату из того же PATCH"
    forecast = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": today.isoformat(), "horizon_days": 30,
    })
    assert forecast.status_code == 202, forecast.text


@pytest.mark.parametrize("status", ["paid", "cancelled"])
def test_terminal_same_amount_and_status_remain_idempotent(client, context, status):
    company, _, account, _ = context
    today = datetime.now(UTC).date().isoformat()
    event = _event(client, company, account, 10000, today)
    path = f"/api/v1/planned-events/{event}"
    assert client.patch(path, json={"status": status}).status_code == 200
    for _ in range(2):
        response = client.patch(path, json={"amount_minor": 10000, "status": status})
        assert response.status_code == 200, response.text
        assert response.json()["remaining_amount_minor"] == 0


def test_partial_amount_reduced_to_confirmed_payment_becomes_paid(client, context):
    company, _, account, _ = context
    today = datetime.now(UTC).date().isoformat()
    event = _event(client, company, account, 15000, today)
    _payment(client, company, account, "100.00", "partial-correction", today)
    reconcile = f"/api/v1/companies/{company}/plan-fact"
    params = {"account_id": account, "as_of": today}
    assert client.post(reconcile, params=params).json()["items"][0]["event"]["status"] == "partially_paid"
    response = client.patch(f"/api/v1/planned-events/{event}", json={"amount_minor": 10000})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"
    assert response.json()["remaining_amount_minor"] == 0
    data = client.get(reconcile, params=params).json()
    assert data["items"][0]["confirmed_amount_minor"] == 10000
    assert len(data["confirmed_matches"]) == 1
    assert not data["proposals"]


@pytest.mark.parametrize("patch", [{"status": "planned"}, {"status": "partially_paid", "amount_minor": 10000}])
def test_explicit_status_cannot_disagree_with_actual_payment(client, context, patch):
    company, _, account, _ = context
    today = datetime.now(UTC).date().isoformat()
    event = _event(client, company, account, 15000, today)
    _payment(client, company, account, "100.00", "status-correction", today)
    reconcile = f"/api/v1/companies/{company}/plan-fact"
    params = {"account_id": account, "as_of": today}
    before = client.post(reconcile, params=params).json()["items"][0]["event"]
    response = client.patch(f"/api/v1/planned-events/{event}", json=patch)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_plan_status"
    assert client.get(reconcile, params=params).json()["items"][0]["event"] == before
