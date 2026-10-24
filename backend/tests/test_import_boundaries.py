"""CSV-ошибки доходят до preview, не становятся500 и не записывают ложный ledger."""

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select, text

from app.core.models import Account, BankTransaction, StatementImport
from app.modules.imports.parser import ColumnMapping
from app.modules.imports.service import ImportService
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


@pytest.mark.parametrize("content,mapping", [
    (b"date,amount\n2026-01-01,1e9\n", {}),
    (b"date,amount\n2026-01-01,1.234\n", {}),
    (b"date,amount,direction\n2026-01-01,100,mystery\n", {"direction": "direction"}),
    (b"date,amount\n2026-01-01,100\n", {"direction": "direction"}),
    (b"date,amount\n2026-01-01,100\n", {"encoding": "not-a-codec"}),
    (b"date,amount\n2026-01-01,90000000000000.01\n", {}),
    (b"date,amount,currency\n2026-01-01,100,USD\n", {"currency": "currency"}),
    (b"date,amount\n2026-01-01,\"100\n", {}),
])
def test_bad_statement_preview_is_safe_and_commit_cannot_write(client, context, session_factory, content, mapping):
    company, _, account, _ = context
    preview = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps({"date": "date", "amount": "amount", **mapping}),
    }, files={"file": ("bad.csv", content, "text/csv")})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] == "failed" and body["error_count"] > 0
    response = client.post(f"/api/v1/imports/{body['import_id']}/commit")
    assert response.status_code == 409 and response.json()["error"]["code"] == "import_failed"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BankTransaction)) == 0


def test_long_bank_id_can_be_committed_without_varchar_overflow(client, context, session_factory):
    company, _, account, _ = context
    external = "x" * 200
    content = f"date,amount,id\n2026-01-01,100,{external}\n".encode()
    preview = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps({"date": "date", "amount": "amount", "external_id": "id"}),
    }, files={"file": ("long-id.csv", content, "text/csv")})
    assert preview.status_code == 200 and preview.json()["error_count"] == 0
    response = client.post(f"/api/v1/imports/{preview.json()['import_id']}/commit")
    assert response.status_code == 200 and response.json()["inserted"] == 1
    with session_factory() as session:
        txn = session.scalar(select(BankTransaction))
        assert txn.external_id == external and len(txn.fingerprint) <= 100


def test_concurrent_same_file_preview_returns_one_import(client, context, session_factory):
    company, _, account, _ = context
    user = client.get("/api/v1/auth/me").json()["id"]

    def preview(_):
        with session_factory.begin() as session:
            return ImportService(session).preview(
                company_id=company, account_id=account, uploaded_by=user, filename="same.csv",
                content=b"date,amount\n2026-01-01,100.00\n", mapping=ColumnMapping(date="date", amount="amount"),
            ).import_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        imports = list(pool.map(preview, range(2)))
    assert imports[0] == imports[1]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(StatementImport)) == 1


def test_filename_over_storage_limit_is_422(client, context):
    company, _, account, _ = context
    response = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps({"date": "date", "amount": "amount"}),
    }, files={"file": ("x" * 256, b"date,amount\n2026-01-01,100\n", "text/csv")})
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_import"


def test_preview_waits_for_actual_account_lock(client, context, session_factory):
    company, _, account, _ = context
    user = client.get("/api/v1/auth/me").json()["id"]
    started, state = threading.Event(), {}

    def preview():
        with session_factory.begin() as session:
            state["pid"] = session.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            return ImportService(session).preview(
                company_id=company, account_id=account, uploaded_by=user, filename="locked.csv",
                content=b"date,amount\n2026-01-01,100.00\n", mapping=ColumnMapping(date="date", amount="amount"),
            ).import_id
    with session_factory() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.scalar(select(Account).where(Account.id == uuid.UUID(account)).with_for_update())
        future = pool.submit(preview)
        try:
            assert started.wait(5)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with session_factory() as observer:
                    blocked = observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), state)
                if blocked:
                    break
                assert not future.done(), "Preview прошёл без блокировки счёта"
                time.sleep(0.01)
            else:
                raise AssertionError("Не наблюдается реальная блокировка PostgreSQL")
        finally:
            holder.rollback()
        assert future.result(timeout=5)
