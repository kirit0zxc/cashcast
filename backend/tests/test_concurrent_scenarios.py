"""Две вкладки не должны создавать разные задания для одного сценария."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text

from app.core.models import ForecastRun, Job
from tests.test_integration import _run_worker_until_idle, logged_in


def test_concurrent_identical_scenarios_return_one_run_and_job(client, session_factory, engine):
    context = logged_in.__wrapped__(client, session_factory)
    accepted = client.post(f"/api/v1/companies/{context['company_id']}/forecasts", json={
        "account_id": context["account_id"], "as_of": "2026-03-01", "horizon_days": 30,
    })
    assert accepted.status_code == 202, accepted.text
    base_id = accepted.json()["forecast_run_id"]
    _run_worker_until_idle(session_factory)
    body = {"changes": [{"kind": "add_expense", "amount_minor": 10000,
                          "on_date": date(2026, 3, 5).isoformat()}]}
    read_started, release_first = threading.Event(), threading.Event()
    hook_lock = threading.Lock()
    state = {"paused": False}

    def pause_first_lookup(connection, cursor, statement, parameters, context, executemany):
        # Удерживаем результат первого чтения до вставки. Второй запрос либо ждёт
        # account lock, либо успевает записать дубль; фиксированный sleep не нужен.
        if "SELECT forecast_run." not in statement or "forecast_run.scenario_hash =" not in statement:
            return
        with hook_lock:
            if state["paused"]:
                return
            state["paused"] = True
        read_started.set()
        assert release_first.wait(10), "Первое чтение не было освобождено"

    def request():
        # Отдельный клиент/сессия на вкладку; lifespan общей app повторно не запускаем.
        tab = TestClient(client.app, raise_server_exceptions=False)
        tab.cookies.update(client.cookies)
        tab.headers.update({"X-CSRF-Token": client.headers["X-CSRF-Token"]})
        return tab.post(f"/api/v1/forecasts/{base_id}/scenarios", json=body)

    event.listen(engine, "after_cursor_execute", pause_first_lookup)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request)
            assert read_started.wait(10), "Первый запрос не дошёл до поиска сценария"
            second = pool.submit(request)
            try:
                deadline = time.monotonic() + 10
                while not second.done():
                    with session_factory() as observer:
                        blocked = observer.scalar(text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE datname=current_database() AND wait_event_type='Lock' "
                            "AND query LIKE '%account%' AND query LIKE '%FOR UPDATE%')"
                        ))
                    if blocked:
                        break
                    assert time.monotonic() < deadline, "Второй запрос не завершился и не ждёт account lock"
                    time.sleep(0.01)
            finally:
                release_first.set()
            responses = [first.result(timeout=15), second.result(timeout=15)]
    finally:
        release_first.set()
        event.remove(engine, "after_cursor_execute", pause_first_lookup)

    assert [response.status_code for response in responses] == [202, 202], [
        response.text for response in responses
    ]
    jobs = [response.json() for response in responses]
    assert jobs[0]["forecast_run_id"] == jobs[1]["forecast_run_id"]
    assert jobs[0]["job_id"] == jobs[1]["job_id"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ForecastRun).where(
            ForecastRun.base_forecast_id == base_id,
        )) == 1
        assert session.scalar(select(func.count()).select_from(Job).where(
            Job.dedupe_key == f"forecast:{jobs[0]['forecast_run_id']}",
        )) == 1
    _run_worker_until_idle(session_factory)
    result = client.get(f"/api/v1/forecasts/{jobs[0]['forecast_run_id']}").json()
    assert result["status"] == "succeeded"
    assert result["base_forecast_id"] == base_id and len(result["points"]) == 30
