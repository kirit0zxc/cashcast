"""Календарно невозможный перенос отклоняется до создания заведомо failed job."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.core.models import ForecastRun, Job
from tests.test_accounts import account_context
from tests.test_integration import _run_worker_until_idle


@pytest.mark.parametrize("due,shifts,status", [
    ("9999-12-31", [1], 422), ("9999-12-30", [2], 422),
    ("9999-12-31", [0], 202), ("9999-12-30", [1], 202),
    ("9999-12-30", [1, 1], 422), ("9999-12-30", [0, 1], 202), ("9999-12-30", [1, 0], 202),
])
def test_delay_calendar_preflight_without_rejecting_valid_boundary(client, session_factory, due, shifts, status):
    company, _, account, _ = account_context.__wrapped__(client, session_factory)
    event = client.post(f"/api/v1/companies/{company}/planned-events", json={
        "account_id": account, "direction": "out", "amount_minor": 10000, "due_date": due,
    })
    assert event.status_code == 201, event.text
    as_of = datetime.now(UTC).date().isoformat()
    base = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": as_of, "horizon_days": 30,
    })
    assert base.status_code == 202, base.text
    _run_worker_until_idle(session_factory)
    base_id = base.json()["forecast_run_id"]
    before = client.get(f"/api/v1/forecasts/{base_id}").json()
    assert before["status"] == "succeeded"
    with session_factory() as session:
        counts = (session.scalar(select(func.count()).select_from(ForecastRun)),
                  session.scalar(select(func.count()).select_from(Job)))
    response = client.post(f"/api/v1/forecasts/{base_id}/scenarios", json={
        "changes": [{"kind": "delay_event", "target_id": event.json()["id"], "shift_days": shift} for shift in shifts],
    })
    assert response.status_code == status, response.text
    if status == 422:
        assert response.json()["error"]["code"] == "invalid_scenario"
        with session_factory() as session:
            assert counts == (session.scalar(select(func.count()).select_from(ForecastRun)),
                              session.scalar(select(func.count()).select_from(Job)))
            assert session.get(ForecastRun, uuid.UUID(base_id)).as_of == date.fromisoformat(as_of)
    else:
        _run_worker_until_idle(session_factory)
        scenario = client.get(f"/api/v1/forecasts/{response.json()['forecast_run_id']}").json()
        assert scenario["status"] == "succeeded" and scenario["base_forecast_id"] == base_id
    assert client.get(f"/api/v1/forecasts/{base_id}").json() == before


def test_separate_targets_keep_independent_dates_in_composed_scenario(client, session_factory):
    company, _, account, _ = account_context.__wrapped__(client, session_factory)
    targets = []
    for _ in range(2):
        created = client.post(f"/api/v1/companies/{company}/planned-events", json={
            "account_id": account, "direction": "out", "amount_minor": 10000, "due_date": "9999-12-30",
        })
        assert created.status_code == 201, created.text
        targets.append(created.json()["id"])
    base = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": datetime.now(UTC).date().isoformat(), "horizon_days": 30,
    })
    assert base.status_code == 202, base.text
    _run_worker_until_idle(session_factory)
    response = client.post(f"/api/v1/forecasts/{base.json()['forecast_run_id']}/scenarios", json={
        "changes": [{"kind": "delay_event", "target_id": target, "shift_days": 1} for target in targets],
    })
    assert response.status_code == 202, response.text
    _run_worker_until_idle(session_factory)
    scenario = client.get(f"/api/v1/forecasts/{response.json()['forecast_run_id']}").json()
    assert scenario["status"] == "succeeded"
    assert all(item["due_date"] == "9999-12-30" for item in
               client.get(f"/api/v1/companies/{company}/planned-events").json())
