"""Границы сессии/компании для сквозного сценария и безопасные ошибки ввода."""

import uuid
from datetime import date

import pytest

from app.core.models import ForecastRun, Job
from tests.factories import make_account, make_company
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def test_foreign_forecasts_jobs_and_accounts_are_not_disclosed(client, session_factory, context):
    own, _, _account, _ = context
    with session_factory.begin() as session:
        other = make_company(session, "Изолированная")
        foreign_account = make_account(session, other)
        run = ForecastRun(company_id=other.id, account_id=foreign_account.id,
                          as_of=date(2026, 1, 1), horizon_days=30, data_version="private",
                          model_version="private", seed=42, status="pending")
        session.add(run)
        session.flush()
        job = Job(company_id=other.id, kind="forecast", payload={"forecast_run_id": str(run.id)})
        session.add(job)
        session.flush()
        run_id, job_id, account_id = str(run.id), str(job.id), str(foreign_account.id)
    for path in [f"/forecasts/{run_id}", f"/forecasts/{run_id}/explanations",
                 f"/forecasts/{run_id}/comparison", f"/jobs/{job_id}"]:
        assert client.get(f"/api/v1{path}").status_code == 404
    response = client.post(f"/api/v1/companies/{own}/forecasts", json={
        "account_id": account_id, "as_of": "2026-01-01", "horizon_days": 30,
    })
    assert response.status_code == 404
    assert client.get(f"/api/v1/companies/{own}/plan-fact",
                      params={"account_id": account_id, "as_of": "2026-01-01"}).status_code == 404
    assert client.post(f"/api/v1/forecasts/{run_id}/scenarios", json={
        "changes": [{"kind": "add_expense", "amount_minor": 1, "on_date": "2026-01-02"}],
    }).status_code == 404


def test_invalid_mapping_and_missing_csrf_are_expected_errors(client, context):
    own, _, account, _ = context
    for mapping in ["{", '{"date":"date","delimiter":";;"}']:
        response = client.post(f"/api/v1/companies/{own}/imports", data={
            "account_id": account, "mapping": mapping,
        }, files={"file": ("invalid.csv", b"date,amount\n2026-01-01,1\n", "text/csv")})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_mapping"
    client.headers.pop("X-CSRF-Token")
    response = client.post(f"/api/v1/companies/{own}/planned-events", json={
        "account_id": account, "amount_minor": 100, "direction": "out", "due_date": "2026-11-01",
    })
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert client.get(f"/api/v1/forecasts/{uuid.uuid4()}").status_code == 404
