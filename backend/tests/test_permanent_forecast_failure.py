"""Неизменяемый некорректный вход не исправляется повтором того же задания."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.models import ForecastPoint, ForecastRun, Job
from app.modules.forecasting.service import UnsupportedModelVersionError
from app.modules.forecasting.v2.quality import ForecastInputError
from app.modules.jobs import queue
from app.modules.jobs.handlers import HANDLERS
from app.modules.jobs.worker import run_once
from tests.test_accounts import account_context


def _accepted(client, session_factory):
    company, _, account, _ = account_context.__wrapped__(client, session_factory)
    response = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": "2026-09-30", "horizon_days": 30,
    })
    assert response.status_code == 202, response.text
    accepted = response.json()
    with session_factory.begin() as session:
        session.get(Job, accepted["job_id"]).max_attempts = 5
    return accepted


@pytest.mark.parametrize("failure,code", [
    (ForecastInputError("forecast_resource_limit", "PRIVATE-INPUT-DO-NOT-LOG"), "forecast_resource_limit"),
    (UnsupportedModelVersionError(), "unsupported_model_version"),
])
def test_permanent_forecast_failure_finishes_both_records_on_first_attempt(
    client, session_factory, monkeypatch, caplog, failure, code,
):
    accepted = _accepted(client, session_factory)

    def broken(session, payload):
        run = session.get(ForecastRun, payload["forecast_run_id"])
        run.opening_balance_minor = 123456
        session.flush()
        raise failure

    monkeypatch.setitem(HANDLERS, "forecast", broken)
    assert run_once(session_factory, worker_id="permanent", lease_seconds=300)
    with session_factory() as session:
        job = session.get(Job, accepted["job_id"])
        run = session.get(ForecastRun, accepted["forecast_run_id"])
        assert job.status == run.status == "failed"
        assert job.attempts == 1 < job.max_attempts
        assert job.last_error == run.error_code == code
        assert job.finished_at is not None and run.finished_at is not None and job.lease_until is None
        assert run.opening_balance_minor is None
        assert session.scalar(select(func.count()).select_from(ForecastPoint)) == 0
    assert not run_once(session_factory, worker_id="replacement", lease_seconds=300)
    output = client.get(f"/api/v1/jobs/{accepted['job_id']}").json()
    assert output["status"] == "failed" and output["error_code"] == code
    assert "PRIVATE-INPUT-DO-NOT-LOG" not in caplog.text


def test_temporary_failure_still_retries_frozen_input_and_then_succeeds(client, session_factory, monkeypatch):
    accepted = _accepted(client, session_factory)
    original = HANDLERS["forecast"]
    calls = 0

    def transient(session, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            session.get(ForecastRun, payload["forecast_run_id"]).opening_balance_minor = 123456
            session.flush()
            raise ConnectionError("PRIVATE-INPUT-DO-NOT-LOG")
        return original(session, payload)

    monkeypatch.setitem(HANDLERS, "forecast", transient)
    assert run_once(session_factory, worker_id="temporary", lease_seconds=300)
    with session_factory.begin() as session:
        job = session.get(Job, accepted["job_id"])
        run = session.get(ForecastRun, accepted["forecast_run_id"])
        assert job.status == "pending" and run.status == "pending"
        assert job.attempts == 1 and job.finished_at is None and run.finished_at is None
        assert job.last_error == "ConnectionError" and run.opening_balance_minor is None
        job.run_after = datetime.now(UTC) - timedelta(seconds=1)
    assert run_once(session_factory, worker_id="recovered", lease_seconds=300)
    with session_factory() as session:
        job = session.get(Job, accepted["job_id"])
        run = session.get(ForecastRun, accepted["forecast_run_id"])
        assert job.status == run.status == "succeeded" and job.attempts == 2
        assert session.scalar(select(func.count()).select_from(ForecastPoint)) == 30


def test_forecast_error_class_does_not_change_retry_policy_of_other_job_kinds(session_factory, monkeypatch):
    def probe(session, payload):
        raise ForecastInputError("invalid_forecast_input", "Синтетическое исключение другого обработчика")

    monkeypatch.setitem(HANDLERS, "probe", probe)
    with session_factory.begin() as session:
        job = queue.enqueue(session, kind="probe", payload={}, max_attempts=5)
        job_id = job.id
    assert run_once(session_factory, worker_id="generic", lease_seconds=300)
    with session_factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "pending" and job.attempts == 1
