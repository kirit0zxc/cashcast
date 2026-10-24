"""Банковский ID подтверждает источник, а не разрешает молча менять финансовый факт."""

import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.models import BankTransaction, DailyBalance
from app.modules.imports.service import ImportService
from tests.test_accounts import account_context

MAPPING = {"date": "date", "amount": "amount", "direction": "direction", "currency": "currency",
           "external_id": "id", "counterparty_name": "name", "counterparty_ref": "inn",
           "purpose": "purpose", "balance": "balance"}
ORIGINAL = {"date": "2026-01-01", "amount": "100.00", "direction": "in", "currency": "RUB",
            "id": "bank-private-fixed", "name": "Контрагент", "inn": "00123",
            "purpose": "Закрытые данные источника", "balance": "500.00"}


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _preview(client, context, rows):
    company, _, account, _ = context
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(ORIGINAL))
    writer.writeheader()
    writer.writerows(rows)
    response = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps(MAPPING),
    }, files={"file": ("synthetic.csv", output.getvalue().encode("utf-8-sig"), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def _commit(client, preview):
    return client.post(f"/api/v1/imports/{preview['import_id']}/commit")


@pytest.mark.parametrize("changed", [
    {"date": "2026-01-02"}, {"amount": "200.00"}, {"direction": "out"},
    {"name": "Другой контрагент"}, {"inn": "00456"}, {"purpose": "Другое назначение"},
])
@pytest.mark.parametrize("bank_id", [ORIGINAL["id"], "x" * 200])
def test_changed_bank_payload_is_atomic_conflict(client, context, session_factory, changed, bank_id):
    row = {**ORIGINAL, "id": bank_id}
    assert _commit(client, _preview(client, context, [row])).status_code == 200
    # Хорошая новая строка перед конфликтом тоже не должна попасть в ledger.
    altered = _preview(client, context, [
        {**ORIGINAL, "id": "new-private-row", "balance": "900.00"},
        {**row, **changed, "balance": "999.00"},
    ])
    assert altered["error_count"] == 0
    response = _commit(client, altered)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "transaction_id_conflict"
    assert ORIGINAL["purpose"] not in response.text and bank_id not in response.text
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BankTransaction)) == 1
        transaction = session.scalar(select(BankTransaction))
        assert transaction.amount_minor == 10000 and transaction.counterparty_ref == "00123"
        balances = session.scalars(select(DailyBalance)).all()
        assert len(balances) == 1 and balances[0].closing_balance_minor == 50000


def test_identical_operation_can_update_separate_balance_without_losing_manual_category(
    client, context, session_factory,
):
    assert _commit(client, _preview(client, context, [ORIGINAL])).status_code == 200
    with session_factory() as session:
        transaction_id = str(session.scalar(select(BankTransaction.id)))
    assert client.patch(f"/api/v1/transactions/{transaction_id}/category",
                        json={"category": "rent"}).status_code == 200
    response = _commit(client, _preview(client, context, [{**ORIGINAL, "balance": "600.00"}]))
    assert response.status_code == 200 and response.json()["inserted"] == 0
    assert response.json()["skipped_existing"] == 1
    with session_factory() as session:
        transaction = session.scalar(select(BankTransaction))
        assert (transaction.category, transaction.category_source) == ("rent", "manual")
        assert transaction.amount_minor == 10000
        assert session.scalar(select(DailyBalance.closing_balance_minor)) == 60000


def test_legacy_foreign_currency_same_bank_id_is_not_silently_skipped(client, context, session_factory):
    assert _commit(client, _preview(client, context, [ORIGINAL])).status_code == 200
    with session_factory.begin() as session:
        session.scalar(select(BankTransaction)).currency = "USD"
    response = _commit(client, _preview(client, context, [{**ORIGINAL, "balance": "600.00"}]))
    assert response.status_code == 409 and response.json()["error"]["code"] == "transaction_id_conflict"
    with session_factory() as session:
        assert session.scalar(select(DailyBalance.closing_balance_minor)) == 50000


def test_conflicting_bank_id_inside_file_fails_preview_and_cannot_commit(client, context, session_factory):
    preview = _preview(client, context, [ORIGINAL, {**ORIGINAL, "amount": "200.00"}])
    assert preview["status"] == "failed" and preview["error_count"] == 1
    assert preview["sample_errors"][0]["field"] == "external_id"
    assert ORIGINAL["id"] not in json.dumps(preview)
    response = _commit(client, preview)
    assert response.status_code == 409 and response.json()["error"]["code"] == "import_failed"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BankTransaction)) == 0
        assert session.scalar(select(func.count()).select_from(DailyBalance)) == 0


def test_identical_bank_id_inside_file_remains_an_ordinary_duplicate(client, context, session_factory):
    preview = _preview(client, context, [ORIGINAL, dict(ORIGINAL)])
    assert preview["error_count"] == 0 and preview["duplicate_in_file"] == 1
    response = _commit(client, preview)
    assert response.status_code == 200 and response.json()["inserted"] == 1
    assert response.json()["skipped_existing"] == 1


def test_parallel_conflicting_files_have_one_winner_and_consistent_balance(client, context, session_factory):
    company, _, _, _ = context
    previews = [_preview(client, context, [{**ORIGINAL, "amount": amount, "balance": amount}])
                for amount in ("100.00", "200.00")]

    def commit(preview):
        try:
            with session_factory.begin() as session:
                ImportService(session).commit(company_id=company, import_id=preview["import_id"])
            return "committed"
        except AppError as exc:
            assert exc.status_code == 409
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, previews)) == ["committed", "transaction_id_conflict"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BankTransaction)) == 1
        assert session.scalar(select(BankTransaction.amount_minor)) == session.scalar(
            select(DailyBalance.closing_balance_minor)
        )
