"""Контракт счетов, изоляция и применение server-side пресета к русской выписке."""

import json

import pytest

from tests.factories import make_account, make_company, make_user


@pytest.fixture
def account_context(client, session_factory):
    with session_factory() as session:
        user = make_user(session, "accounts@example.com", "account-password")
        own = make_company(session, "Собственная", user)
        other = make_company(session, "Чужая")
        a = make_account(session, own, "Альфа")
        b = make_account(session, own, "Бета")
        make_account(session, other, "Недоступный")
        session.commit()
        ids = str(own.id), str(other.id), str(a.id), str(b.id)
    response = client.post("/api/v1/auth/login", json={
        "email": "accounts@example.com", "password": "account-password",
    })
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return ids


def test_account_list_is_scoped_sorted_and_requires_membership(client, account_context):
    own, other, alpha, beta = account_context
    response = client.get(f"/api/v1/companies/{own}/accounts")
    assert response.status_code == 200
    assert response.json()["items"] == [
        {"id": alpha, "company_id": own, "name": "Альфа", "currency": "RUB"},
        {"id": beta, "company_id": own, "name": "Бета", "currency": "RUB"},
    ]
    assert client.get(f"/api/v1/companies/{other}/accounts").status_code == 404


def test_accounts_and_presets_require_session(client):
    assert client.get("/api/v1/companies/00000000-0000-0000-0000-000000000001/accounts").status_code == 401
    assert client.get("/api/v1/import-presets").status_code == 401


def test_server_preset_import_preserves_income_expense_and_leading_zero_inn(client, account_context, session_factory):
    own, _, account, _ = account_context
    preset = client.get("/api/v1/import-presets").json()["items"][0]
    assert preset["id"] == "participants-v1"
    csv = ("operation_id;operation_date;amount;direction;counterparty_name;"
           "counterparty_inn;payment_purpose;balance_eod\n"
           "1;2026-09-01;120.50;Поступление;Покупатель;00123;Оплата;100.00\n"
           "2;2026-09-01;20.50;Списание;Поставщик;00456;Счёт;100.00\n")
    response = client.post(f"/api/v1/companies/{own}/imports", data={
        "account_id": account, "mapping": json.dumps(preset["mapping"]),
    }, files={"file": ("C001.csv", csv.encode("utf-8-sig"), "text/csv")})
    assert response.status_code == 200, response.text
    assert response.json()["error_count"] == 0
    response = client.post(f"/api/v1/imports/{response.json()['import_id']}/commit")
    assert response.status_code == 200
    assert response.json()["inserted"] == 2
    items = client.get(f"/api/v1/companies/{own}/transactions").json()["items"]
    assert sorted((t["direction"], t["amount_minor"]) for t in items) == [("in", 12050), ("out", 2050)]
    from sqlalchemy import select

    from app.core.models import BankTransaction

    with session_factory() as session:
        assert set(session.scalars(select(BankTransaction.counterparty_ref))) == {"00123", "00456"}


def test_cursor_visits_all_transactions_of_the_same_day(client, account_context):
    own, _, account, _ = account_context
    preset = client.get("/api/v1/import-presets").json()["items"][0]
    header = "operation_id;operation_date;amount;direction;balance_eod\n"
    csv = header + "".join(f"{i};2026-09-01;10.00;Поступление;550.00\n" for i in range(55))
    response = client.post(f"/api/v1/companies/{own}/imports", data={
        "account_id": account, "mapping": json.dumps(preset["mapping"]),
    }, files={"file": ("many.csv", csv.encode("utf-8-sig"), "text/csv")})
    assert response.status_code == 200, response.text
    result = client.post(f"/api/v1/imports/{response.json()['import_id']}/commit")
    assert result.json()["inserted"] == 55
    seen = []
    cursor = None
    for _ in range(4):
        params = {"account_id": account, "limit": 25}
        if cursor:
            params["cursor"] = cursor
        page = client.get(f"/api/v1/companies/{own}/transactions", params=params)
        assert page.status_code == 200, page.text
        seen.extend(t["id"] for t in page.json()["items"])
        cursor = page.json()["next_cursor"]
        if not cursor:
            break
    assert cursor is None
    assert len(seen) == len(set(seen)) == 55
    assert client.get(f"/api/v1/companies/{own}/transactions", params={"cursor": "bad"}).status_code == 422
