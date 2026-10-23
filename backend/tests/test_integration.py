"""Интеграционный тест сквозного пути и ключевых гарантий.

Путь: логин → загрузка CSV → commit → запрос прогноза → выполнение задания worker →
GET прогноза отдаёт 30 точек. Плюс: идемпотентность импорта и изоляция компаний.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from tests.factories import make_account, make_company, make_user

PASSWORD = "test-password-123"

_MAPPING = {
    "date": "date",
    "amount": "amount",
    "counterparty_ref": "inn",
    "purpose": "purpose",
    "external_id": "op_id",
    "balance": "balance",
}


def _statement_csv(as_of: date) -> str:
    # 14 дней ежедневных операций и остаток на конец каждого дня.
    lines = ["date,amount,inn,purpose,op_id,balance"]
    balance = 100000  # 1000.00
    for i in range(14, 0, -1):
        d = as_of - timedelta(days=i)
        balance += 50000  # +500.00 приток
        lines.append(f"{d.isoformat()},500.00,7701,Выручка,in{i},{balance / 100:.2f}")
        balance -= 30000  # -300.00 отток
        lines.append(f"{d.isoformat()},-300.00,7702,Расход,out{i},{balance / 100:.2f}")
    return "\n".join(lines) + "\n"


@pytest.fixture
def logged_in(client, session_factory):
    """Создаёт пользователя с компанией и счётом, логинится, возвращает контекст."""
    with session_factory() as s:
        user = make_user(s, "owner@example.com", PASSWORD)
        company = make_company(s, "Моя компания", owner=user)
        account = make_account(s, company)
        s.commit()
        company_id, account_id = str(company.id), str(account.id)

    resp = client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    csrf = resp.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": csrf})
    return {"company_id": company_id, "account_id": account_id}


def _run_worker_until_idle(session_factory) -> None:
    from app.modules.jobs.worker import run_once

    for _ in range(50):
        if not run_once(session_factory, worker_id="test", lease_seconds=300):
            break


def test_full_path_login_import_forecast(client, session_factory, logged_in) -> None:
    company_id = logged_in["company_id"]
    account_id = logged_in["account_id"]
    as_of = date(2026, 3, 1)

    # Импорт выписки.
    files = {"file": ("statement.csv", _statement_csv(as_of), "text/csv")}
    data = {"account_id": account_id, "mapping": json.dumps(_MAPPING)}
    resp = client.post(f"/api/v1/companies/{company_id}/imports", data=data, files=files)
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["status"] == "previewed"
    assert preview["error_count"] == 0
    import_id = preview["import_id"]

    # Commit.
    resp = client.post(f"/api/v1/imports/{import_id}/commit")
    assert resp.status_code == 200, resp.text
    assert resp.json()["inserted"] == 28  # 14 дней * 2 операции

    # Запрос прогноза -> 202 + job.
    resp = client.post(
        f"/api/v1/companies/{company_id}/forecasts",
        json={"account_id": account_id, "as_of": as_of.isoformat(), "horizon_days": 30},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    forecast_id = resp.json()["forecast_run_id"]

    # Выполняем задание (в тестах worker синхронно).
    _run_worker_until_idle(session_factory)

    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.json()["status"] == "succeeded", resp.text

    # Прогноз отдаёт 30 точек.
    resp = client.get(f"/api/v1/forecasts/{forecast_id}")
    assert resp.status_code == 200, resp.text
    forecast = resp.json()
    assert forecast["status"] == "succeeded"
    assert len(forecast["points"]) == 30
    assert forecast["opening_balance_minor"] is not None


def test_reimport_is_idempotent(client, session_factory, logged_in) -> None:
    company_id = logged_in["company_id"]
    account_id = logged_in["account_id"]
    csv_text = _statement_csv(date(2026, 3, 1))
    files = {"file": ("statement.csv", csv_text, "text/csv")}
    data = {"account_id": account_id, "mapping": json.dumps(_MAPPING)}

    r1 = client.post(f"/api/v1/companies/{company_id}/imports", data=data, files=files)
    import_id = r1.json()["import_id"]
    client.post(f"/api/v1/imports/{import_id}/commit")

    # Повторная загрузка того же файла: тот же импорт, commit не добавляет новых операций.
    files2 = {"file": ("statement.csv", csv_text, "text/csv")}
    r2 = client.post(f"/api/v1/companies/{company_id}/imports", data=data, files=files2)
    assert r2.json()["reused"] is True
    assert r2.json()["import_id"] == import_id

    # И прямая повторная загрузка под новый импорт не создаёт дубли операций (fingerprint).
    resp = client.get(f"/api/v1/companies/{company_id}/transactions?limit=200")
    assert len(resp.json()["items"]) == 28


def test_company_isolation(client, session_factory, logged_in) -> None:
    # Чужая компания B, к которой owner@example.com не имеет доступа.
    with session_factory() as s:
        other = make_company(s, "Чужая компания")
        s.commit()
        other_id = str(other.id)

    resp = client.get(f"/api/v1/companies/{other_id}/transactions")
    assert resp.status_code == 404  # 404, а не 403: не раскрываем существование


def test_scenario_creates_separate_run(client, session_factory, logged_in) -> None:
    # Сценарий «что если» считается от зафиксированной базы в отдельный forecast_run.
    company_id = logged_in["company_id"]
    account_id = logged_in["account_id"]
    files = {"file": ("s.csv", _statement_csv(date(2026, 3, 1)), "text/csv")}
    data = {"account_id": account_id, "mapping": json.dumps(_MAPPING)}
    import_id = client.post(
        f"/api/v1/companies/{company_id}/imports", data=data, files=files
    ).json()["import_id"]
    client.post(f"/api/v1/imports/{import_id}/commit")

    base_id = client.post(
        f"/api/v1/companies/{company_id}/forecasts",
        json={"account_id": account_id, "as_of": "2026-03-01", "horizon_days": 30},
    ).json()["forecast_run_id"]
    _run_worker_until_idle(session_factory)

    resp = client.post(
        f"/api/v1/forecasts/{base_id}/scenarios",
        json={"changes": [{"kind": "add_expense", "amount_minor": 100000, "on_date": "2026-03-05"}]},
    )
    assert resp.status_code == 202, resp.text
    scenario_id = resp.json()["forecast_run_id"]
    assert scenario_id != base_id
    _run_worker_until_idle(session_factory)

    scenario = client.get(f"/api/v1/forecasts/{scenario_id}").json()
    assert scenario["status"] == "succeeded"
    assert scenario["base_forecast_id"] == base_id
    assert len(scenario["points"]) == 30


def test_explanations_not_implemented_yet(client, session_factory, logged_in) -> None:
    # Контракт ручки есть, реализация — за Данилом/Димой: ожидаем честный 501.
    company_id = logged_in["company_id"]
    account_id = logged_in["account_id"]
    files = {"file": ("s.csv", _statement_csv(date(2026, 3, 1)), "text/csv")}
    data = {"account_id": account_id, "mapping": json.dumps(_MAPPING)}
    import_id = client.post(
        f"/api/v1/companies/{company_id}/imports", data=data, files=files
    ).json()["import_id"]
    client.post(f"/api/v1/imports/{import_id}/commit")
    forecast_id = client.post(
        f"/api/v1/companies/{company_id}/forecasts",
        json={"account_id": account_id, "as_of": "2026-03-01", "horizon_days": 30},
    ).json()["forecast_run_id"]
    resp = client.get(f"/api/v1/forecasts/{forecast_id}/explanations")
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "not_implemented"
