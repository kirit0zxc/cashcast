"""Настоящие импорт, очередь, замороженный факт и tenant-защита проверки."""

import json
from datetime import date, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select

from app.core.models import BankTransaction, CompanyMember, DailyBalance, Job
from app.modules.forecasting.service import DEFAULT_MODEL_VERSION
from tests.factories import make_account, make_company
from tests.test_integration import _run_worker_until_idle
from tests.test_integration import logged_in as login_fixture


@pytest.fixture
def logged_in(client, session_factory):
    return login_fixture.__wrapped__(client, session_factory)


@pytest.fixture
def evaluation_data(client, logged_in):
    start = date(2025, 1, 1)
    rows, balance = ["date,amount,id,balance,purpose"], 1000
    for i in range(110):
        balance -= 13
        rows.append(f"{start + timedelta(days=i)},-13,ev-{i},{balance},CONFIDENTIAL_PURPOSE")
    response = client.post(
        f"/api/v1/companies/{logged_in['company_id']}/imports",
        files={"file": ("checkpoint.csv", "\n".join(rows), "text/csv")},
        data={
            "account_id": logged_in["account_id"],
            "mapping": json.dumps(
                {"date": "date", "amount": "amount", "external_id": "id", "balance": "balance", "purpose": "purpose"}
            ),
        },
    )
    assert response.status_code == 200, response.text
    assert client.post(f"/api/v1/imports/{response.json()['import_id']}/commit").status_code == 200
    return {
        "account_id": logged_in["account_id"],
        "as_of": str(start + timedelta(days=69)),
        "horizon_days": 10,
        "folds": 3,
        "complete_statement": True,
    }


def test_evaluation_roundtrip_frozen_inputs_export_and_repeat(client, session_factory, logged_in, evaluation_data):
    path = f"/api/v1/companies/{logged_in['company_id']}/evaluations"
    accepted = client.post(path, json=evaluation_data)
    assert accepted.status_code == 202, accepted.text
    assert client.post(path, json=evaluation_data).json()["id"] == accepted.json()["id"]
    report_path = accepted.headers["Location"]
    assert client.get(report_path + "/report").status_code == 409
    with session_factory() as session:
        job = session.get(Job, UUID(accepted.json()["id"]))
        assert job.payload["model_version"] == DEFAULT_MODEL_VERSION
        # После enqueue меняем будущие факты: worker обязан использовать frozen-набор.
        balance = session.scalar(
            select(DailyBalance).where(
                DailyBalance.account_id == UUID(logged_in["account_id"]), DailyBalance.balance_date == date(2025, 3, 12)
            )
        )
        balance.closing_balance_minor = 999_999_999
        session.commit()
    _run_worker_until_idle(session_factory)
    status = client.get(report_path)
    assert status.json()["status"] == "succeeded", status.text
    report = status.json()["report"]
    assert report["regression"]["balance"]["n"] == 30
    assert report["windows"][0]["points"][0]["actual_balance_minor"] != 999_999_999
    assert report["model_version"] == DEFAULT_MODEL_VERSION
    assert "CONFIDENTIAL_PURPOSE" not in status.text
    exported = client.get(report_path + "/report?format=json")
    assert exported.json() == report
    assert exported.headers["Cache-Control"] == "private, no-store"
    html = client.get(report_path + "/report?format=html")
    assert html.status_code == 200 and "<svg" in html.text and "CONFIDENTIAL_PURPOSE" not in html.text
    assert client.post(path, json=evaluation_data).json()["id"] != accepted.json()["id"]


def test_auth_csrf_tenant_viewer_and_forecast_period(client, session_factory, logged_in, evaluation_data):
    path = f"/api/v1/companies/{logged_in['company_id']}/evaluations"
    assert client.post(path, json=evaluation_data, headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.post(path, json={**evaluation_data, "horizon_days": 91}).status_code == 422
    assert client.post(path, json={**evaluation_data, "folds": 12}).status_code == 422
    accepted = client.post(path, json=evaluation_data).json()
    with session_factory() as session:
        other = make_company(session, "Другой владелец")
        other_acc = make_account(session, other)
        other_job = Job(kind="evaluation", company_id=other.id, payload={}, status="succeeded", result={"secret": True})
        session.add(other_job)
        session.commit()
        other_id, account_id, job_id = str(other.id), str(other_acc.id), str(other_job.id)
    assert client.post(f"/api/v1/companies/{other_id}/evaluations", json=evaluation_data).status_code == 404
    assert client.post(path, json={**evaluation_data, "account_id": account_id}).status_code == 404
    assert client.get(f"/api/v1/evaluations/{job_id}").status_code == 404
    assert client.get(f"/api/v1/evaluations/{job_id}/report").status_code == 404
    with session_factory() as session:
        member = session.scalar(select(CompanyMember).where(CompanyMember.company_id == UUID(logged_in["company_id"])))
        member.role = "viewer"
        session.commit()
    assert client.post(path, json=evaluation_data).status_code == 403
    assert client.get(f"/api/v1/evaluations/{accepted['id']}").status_code == 200
    client.cookies.clear()
    assert client.get(f"/api/v1/evaluations/{accepted['id']}").status_code == 401


def test_end_without_operations_inside_covered_period(client, session_factory, logged_in, evaluation_data):
    cutoff = date.fromisoformat(evaluation_data["as_of"])
    end = cutoff + timedelta(days=2)
    with session_factory() as session:
        session.execute(
            delete(BankTransaction).where(
                BankTransaction.account_id == UUID(logged_in["account_id"]),
                BankTransaction.booked_on > cutoff,
                BankTransaction.booked_on <= end,
            )
        )
        session.execute(
            delete(DailyBalance).where(
                DailyBalance.account_id == UUID(logged_in["account_id"]),
                DailyBalance.balance_date > cutoff,
                DailyBalance.balance_date <= end,
            )
        )
        session.commit()
    accepted = client.post(
        f"/api/v1/companies/{logged_in['company_id']}/evaluations",
        json={**evaluation_data, "folds": 1, "horizon_days": 2},
    )
    assert accepted.status_code == 202, accepted.text
    with session_factory() as session:
        job = session.get(Job, UUID(accepted.json()["id"]))
        assert all(t["booked_on"] <= str(end) for t in job.payload["transactions"])
        assert all(b["date"] <= str(end) for b in job.payload["balances"])
    _run_worker_until_idle(session_factory)
    report = client.get(accepted.headers["Location"]).json()["report"]
    assert report["regression"]["balance"]["n"] == 2
    assert all(p["balance_source"] == "reconstructed" for p in report["windows"][0]["points"])


def test_failed_evaluation_can_be_retried_without_changing_snapshot(
    client, session_factory, logged_in, evaluation_data
):
    path = f"/api/v1/companies/{logged_in['company_id']}/evaluations"
    accepted = client.post(path, json=evaluation_data).json()
    with session_factory() as session:
        job = session.get(Job, UUID(accepted["id"]))
        original = job.payload
        job.status = "failed"
        job.attempts = job.max_attempts
        job.last_error = "lease_expired_attempts_exhausted"
        session.commit()
    retried = client.post(path, json=evaluation_data)
    assert retried.status_code == 202
    assert retried.json()["id"] == accepted["id"]
    assert retried.json()["status"] == "pending"
    with session_factory() as session:
        job = session.get(Job, UUID(accepted["id"]))
        assert job.payload == original and job.attempts == 0 and job.last_error is None
    _run_worker_until_idle(session_factory)
    assert client.get(f"/api/v1/evaluations/{accepted['id']}").json()["status"] == "succeeded"
    history = client.get(f"{path}?account_id={logged_in['account_id']}")
    assert [item["id"] for item in history.json()] == [accepted["id"]]
