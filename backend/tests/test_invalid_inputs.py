"""Ошибки пользовательского ввода не становятся500или неисполняемыми заданиями."""

import json
import uuid

import pytest

from app.api.schemas.models import ScenarioRequest
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


@pytest.mark.parametrize("endpoint", ["forecast", "plan", "import", "transactions"])
def test_invalid_account_id_is_validation_error(client, context, endpoint):
    company, _, _, _ = context
    base = f"/api/v1/companies/{company}"
    if endpoint == "forecast":
        response = client.post(base + "/forecasts", json={"account_id": "not-uuid", "as_of": "2026-09-30"})
    elif endpoint == "plan":
        response = client.post(base + "/planned-events", json={
            "account_id": "not-uuid", "direction": "out", "amount_minor": 100, "due_date": "2026-11-01",
        })
    elif endpoint == "import":
        response = client.post(base + "/imports", data={
            "account_id": "not-uuid", "mapping": json.dumps({"date": "date", "amount": "amount"}),
        }, files={"file": ("input.csv", b"date,amount\n2026-09-30,1\n", "text/csv")})
    else:
        response = client.get(base + "/transactions", params={"account_id": "not-uuid"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_oversized_plan_and_seed_rejected_before_database_write(client, context):
    company, _, account, _ = context
    response = client.post(f"/api/v1/companies/{company}/planned-events", json={
        "account_id": account, "direction": "out", "amount_minor": 10**40, "due_date": "2026-11-01",
    })
    assert response.status_code == 422
    response = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": "2026-09-30", "seed": 10**40,
    })
    assert response.status_code == 422


def test_scenario_bounds_and_calendar_underflow_are_validation_errors(client, context):
    company, _, account, _ = context
    response = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": "0001-01-01",
    })
    assert response.status_code == 422
    # До выборки DBцели срабатывает структурная валидация тела сценария.
    for changes in [
        [{"kind": "add_expense", "amount_minor": 10**40, "on_date": "2026-11-01"}],
        [{"kind": "delay_event", "shift_days": 10**40, "target_id": "test"}],
        [{"kind": "reduce_irregular_inflow", "factor": 0.5}] * 51,
    ]:
        response = client.post(f"/api/v1/forecasts/{uuid.uuid4()}/scenarios", json={"changes": changes})
        assert response.status_code == 422
    assert ScenarioRequest(changes=[{"kind": "reduce_irregular_inflow", "factor": 0}]).changes[0].factor == 0
