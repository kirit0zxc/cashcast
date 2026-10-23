"""Последняя смерть worker и истечение lease не оставляют вечный running/двойной расчёт."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.models import ForecastRun, Job
from app.modules.jobs import queue
from app.modules.jobs.handlers import HANDLERS
from app.modules.jobs.worker import run_once
from tests.factories import make_account, make_company


def test_dead_worker_on_last_attempt_finishes_instead_of_hanging(session_factory):
    with session_factory() as session:
        job = queue.enqueue(session, kind="probe", payload={}, max_attempts=1)
        session.commit()
        job_id = job.id
    with session_factory() as session:
        claimed = queue.claim_next(session, worker_id="dead", lease_seconds=1)
        assert claimed.id == job_id
        claimed.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    run_once(session_factory, worker_id="replacement", lease_seconds=300)
    with session_factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "failed"
        assert job.last_error == "lease_expired_attempts_exhausted"
        assert job.finished_at is not None and job.lease_until is None


@pytest.mark.parametrize("max_attempts", [1, 3])
def test_live_handler_holds_job_ownership_even_after_lease_expiry(session_factory, monkeypatch, max_attempts):
    def handler(session, payload):
        # Lease намеренно уже истёк, но живой handler удерживает транзакционную блокировку.
        with session_factory() as competitor:
            assert queue.claim_next(competitor, worker_id="competitor", lease_seconds=300) is None
            competitor.commit()
        # И уборщик последних попыток не должен объявить работающий handler умершим.
        assert not run_once(session_factory, worker_id="reaper", lease_seconds=300)
        return {"checked": True}

    monkeypatch.setitem(HANDLERS, "probe", handler)
    with session_factory() as session:
        job = queue.enqueue(session, kind="probe", payload={}, max_attempts=max_attempts)
        session.commit()
        job_id = job.id
    assert run_once(session_factory, worker_id="live", lease_seconds=-1)
    with session_factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded" and job.attempts == 1
        assert job.result == {"checked": True}


def test_terminal_forecast_error_updates_both_job_and_run(session_factory):
    with session_factory() as session:
        company = make_company(session, "Проверка восстановления")
        account = make_account(session, company)
        run = ForecastRun(company_id=company.id, account_id=account.id, as_of=date(2026, 9, 30),
                          horizon_days=30, data_version="test", model_version="unavailable",
                          seed=42, status="pending")
        session.add(run)
        session.flush()
        job = queue.enqueue(session, kind="forecast", payload={"forecast_run_id": str(run.id)}, max_attempts=1)
        session.commit()
        job_id, run_id = job.id, run.id
    assert run_once(session_factory, worker_id="test", lease_seconds=300)
    with session_factory() as session:
        assert session.get(Job, job_id).status == "failed"
        run = session.get(ForecastRun, run_id)
        assert run.status == "failed" and run.finished_at is not None
        assert run.error_code == "ValueError"
