"""Явный повтор owner восстанавливает только временную ошибку, не меняя frozen input и fencing."""

import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.models import CompanyMember, ForecastPoint, ForecastRun, Job
from app.modules.forecasting.v2.quality import ForecastInputError
from app.modules.jobs.handlers import HANDLERS
from app.modules.jobs.worker import run_once
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _request(client, context):
    path = f"/api/v1/companies/{context[0]}/forecasts"
    body = {"account_id": context[2], "as_of": "2026-09-30", "horizon_days": 30}
    response = client.post(path, json=body)
    assert response.status_code == 202, response.text
    return path, body, response.json()


def _exhaust(session_factory, monkeypatch, accepted, failure=None):
    def fail(_session, _payload):
        raise failure or ConnectionError("PRIVATE-SOURCE-NOT-FOR-LOGS")

    with monkeypatch.context() as patch:
        patch.setitem(HANDLERS, "forecast", fail)
        for _ in range(3):
            with session_factory.begin() as db:
                job = db.get(Job, accepted["job_id"])
                if job.status == "failed":
                    break
                job.run_after = datetime.now(UTC) - timedelta(seconds=1)
            assert run_once(session_factory, worker_id="failed-attempt", lease_seconds=10)
    with session_factory() as db:
        job = db.get(Job, accepted["job_id"])
        run = db.get(ForecastRun, accepted["forecast_run_id"])
        assert job.status == run.status == "failed"
        return copy.deepcopy(run.input_snapshot)


def test_repeated_post_recovers_exhausted_transient_job_with_same_input_and_ids(
    client, session_factory, context, monkeypatch,
):
    path, body, accepted = _request(client, context)
    frozen = _exhaust(session_factory, monkeypatch, accepted)
    response = client.post(path, json=body)
    assert response.status_code == 202, response.text
    assert response.json() == {**accepted, "status": "pending"}
    with session_factory() as db:
        job = db.get(Job, accepted["job_id"])
        run = db.get(ForecastRun, accepted["forecast_run_id"])
        assert job.attempts == 3 and job.max_attempts == 6
        assert job.status == run.status == "pending"
        assert job.finished_at is None and run.finished_at is None
        assert job.last_error is None and run.error_code is None
        assert run.input_snapshot == frozen
    assert run_once(session_factory, worker_id="recovered", lease_seconds=10)
    with session_factory() as db:
        assert db.get(Job, accepted["job_id"]).attempts == 4
        assert db.get(ForecastRun, accepted["forecast_run_id"]).input_snapshot == frozen
        assert db.scalar(select(func.count()).select_from(ForecastRun)) == 1
        assert db.scalar(select(func.count()).select_from(ForecastPoint)) == 30
    assert client.get(f"/api/v1/jobs/{accepted['job_id']}").json()["status"] == "succeeded"
    # Успешный повтор не выдаёт ещё один бюджет и не переписывает сохранённый результат.
    before = client.get(f"/api/v1/forecasts/{accepted['forecast_run_id']}").json()
    assert client.post(path, json=body).json()["status"] == "succeeded"
    assert client.get(f"/api/v1/forecasts/{accepted['forecast_run_id']}").json() == before


@pytest.mark.parametrize("failure", [
    ForecastInputError("forecast_resource_limit", "synthetic"), RuntimeError("synthetic"),
])
def test_permanent_or_unclassified_failure_does_not_get_more_attempts(
    client, session_factory, context, monkeypatch, failure,
):
    path, body, accepted = _request(client, context)
    frozen = _exhaust(session_factory, monkeypatch, accepted, failure)
    with session_factory() as db:
        attempts = db.get(Job, accepted["job_id"]).attempts
    assert client.post(path, json=body).json()["status"] == "failed"
    with session_factory() as db:
        job = db.get(Job, accepted["job_id"])
        assert job.attempts == attempts and job.max_attempts == 3
        assert db.get(ForecastRun, accepted["forecast_run_id"]).input_snapshot == frozen


def test_concurrent_explicit_repeats_grant_only_one_new_retry_budget(client, session_factory, context, monkeypatch):
    path, body, accepted = _request(client, context)
    _exhaust(session_factory, monkeypatch, accepted)

    def repeat(_):
        response = client.post(path, json=body)
        assert response.status_code == 202, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(repeat, range(2))) == [{**accepted, "status": "pending"}] * 2
    with session_factory() as db:
        job = db.get(Job, accepted["job_id"])
        assert job.attempts == 3 and job.max_attempts == 6


def test_viewer_cannot_restart_failed_job(client, session_factory, context, monkeypatch):
    path, body, accepted = _request(client, context)
    _exhaust(session_factory, monkeypatch, accepted)
    user = client.get("/api/v1/auth/me").json()["id"]
    with session_factory.begin() as db:
        db.get(CompanyMember, {"company_id": uuid.UUID(context[0]), "user_id": uuid.UUID(user)}).role = "viewer"
    assert client.post(path, json=body).status_code == 403
    with session_factory() as db:
        assert db.get(Job, accepted["job_id"]).status == "failed"
        assert db.get(Job, accepted["job_id"]).max_attempts == 3


def test_exhausted_dead_lease_can_be_recovered_by_explicit_request(client, session_factory, context):
    path, body, accepted = _request(client, context)
    with session_factory.begin() as db:
        job = db.get(Job, accepted["job_id"])
        job.status, job.locked_by, job.attempts = "running", "lost-process", 3
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    assert run_once(session_factory, worker_id="reaper", lease_seconds=10)
    assert client.get(f"/api/v1/jobs/{accepted['job_id']}").json()["status"] == "failed"
    response = client.post(path, json=body)
    assert response.json() == {**accepted, "status": "pending"}
    assert run_once(session_factory, worker_id="new-process", lease_seconds=10)
    assert client.get(f"/api/v1/jobs/{accepted['job_id']}").json()["status"] == "succeeded"


def test_failed_scenario_recovers_without_rewriting_its_successful_base(client, session_factory, context, monkeypatch):
    _, _, base = _request(client, context)
    assert run_once(session_factory, worker_id="base", lease_seconds=10)
    base_before = client.get(f"/api/v1/forecasts/{base['forecast_run_id']}").json()
    path = f"/api/v1/forecasts/{base['forecast_run_id']}/scenarios"
    body = {"changes": [{"kind": "add_expense", "amount_minor": 100, "on_date": "2026-10-01"}]}
    accepted = client.post(path, json=body).json()
    frozen = _exhaust(session_factory, monkeypatch, accepted)
    response = client.post(path, json=body)
    assert response.json() == {**accepted, "status": "pending"}
    assert run_once(session_factory, worker_id="scenario-recovered", lease_seconds=10)
    assert client.get(f"/api/v1/forecasts/{base['forecast_run_id']}").json() == base_before
    with session_factory() as db:
        assert db.get(ForecastRun, accepted["forecast_run_id"]).input_snapshot == frozen
    assert client.get(f"/api/v1/forecasts/{accepted['forecast_run_id']}/comparison").status_code == 200


def test_retry_is_rolled_back_with_its_http_transaction(client, session_factory, context, monkeypatch):
    from app.modules.jobs.recovery import ForecastRetryRecovery

    path, body, accepted = _request(client, context)
    frozen = _exhaust(session_factory, monkeypatch, accepted)
    original = ForecastRetryRecovery.resume

    def fail_after_recovery(service, run, job):
        assert original(service, run, job)
        raise AppError(409, "synthetic_rollback", "Синтетическая проверка rollback")

    monkeypatch.setattr(ForecastRetryRecovery, "resume", fail_after_recovery)
    assert client.post(path, json=body).status_code == 409
    with session_factory() as db:
        job, run = db.get(Job, accepted["job_id"]), db.get(ForecastRun, accepted["forecast_run_id"])
        assert job.status == run.status == "failed"
        assert job.attempts == job.max_attempts == 3
        assert run.input_snapshot == frozen


def test_legacy_failed_run_without_snapshot_is_not_backfilled_or_retried(client, session_factory, context, monkeypatch):
    path, body, accepted = _request(client, context)
    _exhaust(session_factory, monkeypatch, accepted)
    with session_factory.begin() as db:
        db.get(ForecastRun, accepted["forecast_run_id"]).input_snapshot = None
    assert client.post(path, json=body).json()["status"] == "failed"
    with session_factory() as db:
        assert db.get(Job, accepted["job_id"]).max_attempts == 3
        assert db.get(ForecastRun, accepted["forecast_run_id"]).input_snapshot is None


def test_repeat_does_not_wait_for_live_handler_job_lock(client, session_factory, context, monkeypatch):
    from sqlalchemy import text

    path, body, accepted = _request(client, context)
    entered, release = threading.Event(), threading.Event()
    original_handler = HANDLERS["forecast"]

    def waiting_handler(db, payload):
        entered.set()
        assert release.wait(6), "HTTP повтор не должен ждать живой handler"
        return original_handler(db, payload)

    def bounded_factory():
        db = session_factory()
        db.execute(text("SET LOCAL lock_timeout = '1s'"))
        return db

    monkeypatch.setitem(HANDLERS, "forecast", waiting_handler)
    monkeypatch.setattr(client.app.state, "session_factory", bounded_factory)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(run_once, session_factory, worker_id="live", lease_seconds=10)
        try:
            assert entered.wait(6)
            response = client.post(path, json=body)
        finally:
            release.set()
        assert worker.result(timeout=8)
    assert response.status_code == 202, response.text
    assert response.json() == {**accepted, "status": "running"}
