"""Старый fingerprint без ID не разрешает молча потерять факт другого контрагента."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.models import BankTransaction, DailyBalance
from app.modules.imports.service import ImportService
from tests.test_accounts import account_context
from tests.test_statement_conflicts import ORIGINAL, _commit, _preview


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


FIRST = {**ORIGINAL, "id": "", "inn": "", "name": "Первый синтетический поставщик"}
SECOND = {**FIRST, "name": "Второй синтетический поставщик"}


def test_different_name_same_no_id_key_fails_whole_preview(client, context, session_factory):
    preview = _preview(client, context, [FIRST, SECOND])
    assert preview["status"] == "failed" and preview["error_count"] == 1
    assert _commit(client, preview).status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(BankTransaction)) == 0


def test_different_name_same_old_key_conflicts_atomically_without_new_identity(client, context, session_factory):
    assert _commit(client, _preview(client, context, [FIRST])).status_code == 200
    with session_factory() as db:
        original_fingerprint = db.scalar(select(BankTransaction.fingerprint))
    preview = _preview(client, context, [
        {**ORIGINAL, "id": "good-extra-operation", "balance": "900.00"}, {**SECOND, "balance": "999.00"},
    ])
    response = _commit(client, preview)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "transaction_fingerprint_conflict"
    assert FIRST["name"] not in response.text and SECOND["name"] not in response.text
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(BankTransaction)) == 1
        assert db.scalar(select(BankTransaction.fingerprint)) == original_fingerprint
        assert db.scalar(select(BankTransaction.counterparty_name)) == FIRST["name"]
        assert db.scalar(select(DailyBalance.closing_balance_minor)) == 50000


def test_identical_no_id_repeat_keeps_manual_category_and_separate_eod(client, context, session_factory):
    assert _commit(client, _preview(client, context, [FIRST])).status_code == 200
    with session_factory() as db:
        transaction = db.scalar(select(BankTransaction))
        identifier, original_fingerprint = str(transaction.id), transaction.fingerprint
    assert client.patch(f"/api/v1/transactions/{identifier}/category", json={"category": "rent"}).status_code == 200
    response = _commit(client, _preview(client, context, [{**FIRST, "balance": "600.00"}]))
    assert response.status_code == 200 and response.json()["inserted"] == 0
    with session_factory() as db:
        transaction = db.scalar(select(BankTransaction))
        assert (transaction.fingerprint, transaction.category, transaction.category_source) == (
            original_fingerprint, "rent", "manual",
        )
        assert db.scalar(select(DailyBalance.closing_balance_minor)) == 60000


def test_concurrent_no_id_conflict_has_only_one_winner(client, context, session_factory):
    previews = [_preview(client, context, [row]) for row in (FIRST, SECOND)]

    def commit(preview):
        try:
            with session_factory.begin() as db:
                ImportService(db).commit(company_id=context[0], import_id=preview["import_id"])
            return "committed"
        except AppError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, previews)) == ["committed", "transaction_fingerprint_conflict"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(BankTransaction)) == 1
