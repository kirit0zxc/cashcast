"""Проверяем блокировку реальных PostgreSQL-сессий во время чтения входа/правки категории."""

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.api.schemas.models import TransactionCategoryPatch
from app.api.v1.transactions import patch_category
from app.core.auth import CurrentUser
from app.core.models import BankTransaction
from app.modules.categorization.service import get_categorizer
from app.modules.forecasting.snapshot import build_snapshot
from app.modules.imports.service import ImportService
from app.modules.integration.categories import TransactionCategorization
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _preview(client, company, account, operation_id, balance):
    today = datetime.now(UTC).date().isoformat()
    csv = f"operation_id;operation_date;amount;direction;balance_eod\n{operation_id};{today};10;Поступление;{balance}\n"
    preset = client.get("/api/v1/import-presets").json()["items"][0]["mapping"]
    response = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps(preset),
    }, files={"file": ("lock.csv", csv.encode("utf-8-sig"), "text/csv")})
    assert response.status_code == 200
    return response.json()["import_id"]


def _blocked_categorizer(factory, writer_started, state):
    delegate = get_categorizer()

    class WaitingCategorizer:
        def categorize(self, txns):
            state["reader_ready"].set()
            assert writer_started.wait(5), "Второй поток не начал запись"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with factory() as observer:
                    blocked = observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                              {"pid": state["writer_pid"]})
                if blocked:
                    return delegate.categorize(txns)
                assert not state["writer_done"].is_set(), "Запись прошла внутри чтения без блокировки"
                time.sleep(0.01)
            raise AssertionError("Не наблюдается ожидаемая блокировка PostgreSQL")
    return WaitingCategorizer()


@pytest.mark.parametrize("operation", ["snapshot", "category"])
def test_snapshot_and_manual_category_serialize_with_import(client, session_factory, context, monkeypatch, operation):
    company, _, account, _ = context
    initial = _preview(client, company, account, "initial", "100")
    assert client.post(f"/api/v1/imports/{initial}/commit").status_code == 200
    pending = _preview(client, company, account, "next", "200")
    writer_started = threading.Event()
    state = {"reader_ready": threading.Event(), "writer_done": threading.Event()}
    user_id = client.get("/api/v1/auth/me").json()["id"]
    with session_factory() as session:
        transaction_id = session.scalar(select(BankTransaction.id))

    module = "app.modules.forecasting.snapshot" if operation == "snapshot" else "app.modules.integration.categories"
    # Фабрика блокирует только читателя; writer import также категоризирует и использует обычную фабрику.
    reader_thread = {}
    waiting = _blocked_categorizer(session_factory, writer_started, state)
    monkeypatch.setattr(f"{module}.get_categorizer", lambda: waiting
                        if threading.get_ident() == reader_thread.get("id") else get_categorizer())

    def read():
        reader_thread["id"] = threading.get_ident()
        with session_factory.begin() as session:
            if operation == "snapshot":
                data = build_snapshot(session, account_id=account, as_of=datetime.now(UTC).date(),
                                      horizon_days=30, seed=42).data
                assert len(data.txns) == 1
                assert data.opening_balance_minor == 10000
            else:
                TransactionCategorization(session).refresh(uuid.UUID(account))

    def write():
        assert state["reader_ready"].wait(5)
        with session_factory.begin() as session:
            state["writer_pid"] = session.scalar(text("SELECT pg_backend_pid()"))
            writer_started.set()
            if operation == "snapshot":
                ImportService(session).commit(import_id=pending, company_id=company)
            else:
                patch_category(transaction_id, TransactionCategoryPatch(category="rent"), session,
                               CurrentUser(user_id, "", "", ""))
        state["writer_done"].set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader, writer = pool.submit(read), pool.submit(write)
        reader.result(timeout=15)
        writer.result(timeout=15)
    if operation == "category":
        with session_factory() as session:
            txn = session.get(BankTransaction, transaction_id)
            assert (txn.category, txn.category_source) == ("rent", "manual")
