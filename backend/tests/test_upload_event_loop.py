"""Один ASGI event loop должен завершать commit, пока другой запрос ждёт account lock."""

import asyncio
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.models import Account
from app.modules.imports.obligations import ObligationImportService
from app.modules.imports.service import ImportService
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


@pytest.mark.parametrize("kind", ["statement", "obligation"])
def test_upload_waiting_for_account_does_not_block_other_request_commit(
    client, session_factory, context, monkeypatch, kind,
):
    company, _, account, _ = context
    locked, release, upload_entered = (threading.Event() for _ in range(3))
    state = {}
    today = datetime.now(UTC).date().isoformat()
    app = client.app

    @app.post("/__test/hold-account")
    def hold_account(session: Session = Depends(get_db, scope="function")):
        # Транзакция освобождается dependency cleanup, а не вручную внутри endpoint.
        session.scalar(select(Account).where(Account.id == uuid.UUID(account)).with_for_update())
        locked.set()
        assert release.wait(6), "Наблюдатель не увидел ожидание account lock"
        return {"released": True}

    service_type = ImportService if kind == "statement" else ObligationImportService
    original = service_type.preview

    def tracked_preview(service, **kwargs):
        # DB timeout ограничивает red-тест: заблокированный event loop не умеет
        # выполнить asyncio.timeout до возврата синхронного SQL-запроса.
        db = service._session if kind == "statement" else service.session
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        state["upload_pid"] = db.scalar(text("SELECT pg_backend_pid()"))
        upload_entered.set()
        return original(service, **kwargs)

    monkeypatch.setattr(service_type, "preview", tracked_preview)
    if kind == "statement":
        preset = client.get("/api/v1/import-presets").json()["items"][0]["mapping"]
        path = f"/api/v1/companies/{company}/imports"
        fields = {"account_id": account, "mapping": json.dumps(preset)}
        content = f"operation_id;operation_date;amount;direction\nloop-check;{today};10;Поступление\n"
    else:
        path = f"/api/v1/companies/{company}/obligation-imports"
        fields = {"account_id": account, "source_name": "event-loop-test"}
        content = ("id;counterparty_ref;direction;amount;currency;due_date;available_at;kind;provenance;tax_regime\n"
                   f"loop-check;test-counterparty;out;10;RUB;{today};{today};invoice;synthetic;\n")

    def observe_and_release():
        assert upload_entered.wait(6), "Preview не начался"
        deadline = time.monotonic() + 6
        try:
            while time.monotonic() < deadline:
                with session_factory() as observer:
                    blocked = observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                              {"pid": state["upload_pid"]})
                if blocked:
                    state["blocked_observed"] = True
                    return
                time.sleep(0.01)
            raise AssertionError("Account lock не наблюдался в PostgreSQL")
        finally:
            release.set()

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                                     cookies=client.cookies, headers=dict(client.headers)) as peer:
            writer = asyncio.create_task(peer.post("/__test/hold-account"))
            assert await asyncio.to_thread(locked.wait, 6), "Writer не получил account lock"
            upload = asyncio.create_task(peer.post(path, data=fields, files={
                "file": ("event-loop.csv", content.encode("utf-8-sig"), "text/csv"),
            }))
            return await asyncio.gather(writer, upload)

    with ThreadPoolExecutor(max_workers=1) as pool:
        observed = pool.submit(observe_and_release)
        try:
            writer_response, upload_response = asyncio.run(invoke())
            observed.result(timeout=8)
        finally:
            release.set()
    assert state.get("blocked_observed"), "Тест обязан воспроизвести реальное ожидание БД"
    assert writer_response.status_code == 200, writer_response.text
    assert upload_response.status_code == 200, upload_response.text
    assert upload_response.json()["error_count"] == 0
