"""Просмотр не смешивает старый остаток плана с только что записанной оплатой."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from tests.test_accounts import account_context
from tests.test_plan_fact_api import _event, _payment


def test_get_plan_fact_is_consistent_with_concurrent_reconcile(client, session_factory, engine):
    company, _, account, _ = account_context.__wrapped__(client, session_factory)
    today = datetime.now(UTC).date().isoformat()
    _event(client, company, account, 10000, today)
    _payment(client, company, account, "100.00", "read-write-race", today)
    path = f"/api/v1/companies/{company}/plan-fact"
    params = {"account_id": account, "as_of": today}
    events_read, release_reader = threading.Event(), threading.Event()
    hook_lock = threading.Lock()
    state = {"paused": False}

    def pause_event_read(connection, cursor, statement, parameters, context, executemany):
        if not statement.startswith("SELECT planned_event.id,"):
            return
        with hook_lock:
            if state["paused"]:
                return
            state["paused"] = True
        events_read.set()
        assert release_reader.wait(10), "Просмотр не освобождён"

    def request(method):
        tab = TestClient(client.app, raise_server_exceptions=False)
        tab.cookies.update(client.cookies)
        tab.headers.update({"X-CSRF-Token": client.headers["X-CSRF-Token"]})
        return tab.request(method, path, params=params)

    event.listen(engine, "after_cursor_execute", pause_event_read)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(request, "GET")
            assert events_read.wait(10), "Просмотр не прочитал план"
            writer = pool.submit(request, "POST")
            try:
                deadline = time.monotonic() + 10
                while not writer.done():
                    with session_factory() as observer:
                        blocked = observer.scalar(text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE datname=current_database() AND wait_event_type='Lock' "
                            "AND query LIKE '%account%' AND query LIKE '%FOR UPDATE%')"
                        ))
                    if blocked:
                        break
                    assert time.monotonic() < deadline, "Сверка не завершилась и не ждёт account lock"
                    time.sleep(0.01)
            finally:
                release_reader.set()
            before, after = reader.result(timeout=15), writer.result(timeout=15)
    finally:
        release_reader.set()
        event.remove(engine, "after_cursor_execute", pause_event_read)

    assert before.status_code == after.status_code == 200, [before.text, after.text]
    for response in (before.json(), after.json()):
        item = response["items"][0]
        assert item["confirmed_amount_minor"] + item["event"]["remaining_amount_minor"] == 10000
    assert before.json()["items"][0]["confirmed_amount_minor"] == 0
    assert before.json()["items"][0]["event"]["remaining_amount_minor"] == 10000
    assert not before.json()["confirmed_matches"]
    assert after.json()["items"][0]["confirmed_amount_minor"] == 10000
    assert after.json()["items"][0]["event"]["remaining_amount_minor"] == 0
