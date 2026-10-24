"""Viewer читает компанию, но CSRF и членство не дают права изменять её данные."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.models import (
    BankTransaction,
    CompanyMember,
    ForecastRun,
    Job,
    ObligationImport,
    PlannedEvent,
    PlannedEventMatch,
    StatementImport,
)
from tests.test_accounts import account_context
from tests.test_statement_conflicts import ORIGINAL, _preview


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def test_viewer_is_read_only_on_company_and_object_write_paths(client, session_factory, context):
    company, other, account, _ = context
    today = datetime.now(UTC).date().isoformat()
    preview = _preview(client, context, [ORIGINAL])
    plan = client.post(f"/api/v1/companies/{company}/planned-events", json={
        "account_id": account, "direction": "out", "amount_minor": 10000, "due_date": today,
    }).json()
    user_id = client.get("/api/v1/auth/me").json()["id"]
    with session_factory.begin() as db:
        transaction = BankTransaction(company_id=uuid.UUID(company), account_id=uuid.UUID(account),
                                      booked_on=datetime.now(UTC).date(), amount_minor=10000,
                                      direction="out", fingerprint="viewer-test")
        run = ForecastRun(company_id=uuid.UUID(company), account_id=uuid.UUID(account),
                          as_of=datetime.now(UTC).date(), horizon_days=30, data_version="viewer-test",
                          model_version="seasonal-guarded-2.0-w84", seed=42, status="succeeded")
        obligation = ObligationImport(company_id=uuid.UUID(company), account_id=uuid.UUID(account),
                                      uploaded_by=uuid.UUID(user_id), source_name="viewer-test",
                                      content_sha256="a" * 64, as_of=datetime.now(UTC).date(),
                                      items=[], errors=[], stats={"total_rows": 0, "valid_count": 0, "error_count": 0})
        db.add_all([transaction, run, obligation])
        db.flush()
        job = Job(company_id=uuid.UUID(company), kind="forecast", status="succeeded",
                  payload={"forecast_run_id": str(run.id)})
        db.add(job)
        db.flush()
        transaction_id, run_id, job_id, obligation_id = map(str, [transaction.id, run.id, job.id, obligation.id])
        db.get(CompanyMember, {"company_id": uuid.UUID(company), "user_id": uuid.UUID(user_id)}).role = "viewer"
        # В другой компании тот же пользователь owner: права проверяются по цели запроса.
        db.add(CompanyMember(company_id=uuid.UUID(other), user_id=uuid.UUID(user_id), role="owner"))

    preset = client.get("/api/v1/import-presets").json()["items"][0]["mapping"]
    company_path = f"/api/v1/companies/{company}"
    params = {"account_id": account, "as_of": today}
    requests = [
        ("POST", company_path + "/imports", {"data": {"account_id": account, "mapping": json.dumps(preset)},
         "files": {"file": ("viewer.csv", b"operation_date;amount;direction\n", "text/csv")}}),
        ("POST", company_path + "/obligation-imports", {"data": {"account_id": account, "source_name": "viewer"},
         "files": {"file": ("viewer.csv", b"id;amount\n", "text/csv")}}),
        ("POST", f"/api/v1/imports/{preview['import_id']}/commit", {}),
        ("POST", f"/api/v1/obligation-imports/{obligation_id}/commit", {}),
        ("POST", company_path + "/planned-events", {"json": {
            "account_id": account, "direction": "out", "amount_minor": 100, "due_date": today}}),
        ("PATCH", f"/api/v1/planned-events/{plan['id']}", {"json": {"status": "cancelled"}}),
        ("PATCH", f"/api/v1/transactions/{transaction_id}/category", {"json": {"category": "rent"}}),
        ("POST", company_path + "/plan-fact", {"params": params}),
        ("POST", company_path + "/plan-fact/confirm", {"json": {
            "account_id": account, "planned_event_id": plan["id"], "transaction_id": transaction_id,
            "matched_amount_minor": 10000}}),
        ("POST", company_path + "/forecasts", {"json": {**params, "horizon_days": 30}}),
        ("POST", f"/api/v1/forecasts/{run_id}/scenarios", {"json": {"changes": [
            {"kind": "add_expense", "amount_minor": 100, "on_date": today}]}}),
    ]
    for method, path, options in requests:
        response = client.request(method, path, **options)
        assert response.status_code == 403, f"{method} {path}: {response.text}"
        assert response.json()["error"]["code"] == "read_only_company"
    for path in [company_path + "/accounts", company_path + "/planned-events", company_path + "/transactions",
                 company_path + f"/forecasts?account_id={account}", f"/api/v1/jobs/{job_id}",
                 f"/api/v1/forecasts/{run_id}", f"/api/v1/forecasts/{run_id}/explanations"]:
        response = client.get(path)
        assert response.status_code == 200, f"{path}: {response.text}"
    assert client.get(company_path + "/plan-fact", params=params).status_code == 200
    with session_factory() as db:
        assert db.get(StatementImport, uuid.UUID(preview["import_id"])).status == "previewed"
        assert db.get(ObligationImport, uuid.UUID(obligation_id)).status == "previewed"
        assert db.get(PlannedEvent, uuid.UUID(plan["id"])).status == "planned"
        assert db.get(BankTransaction, uuid.UUID(transaction_id)).category is None
        assert db.scalar(select(func.count()).select_from(PlannedEventMatch)) == 0
        assert db.scalar(select(func.count()).select_from(ForecastRun)) == 1
        assert db.scalar(select(func.count()).select_from(Job)) == 1
    # Owner другой компании по-прежнему может создать отдельный company-level план.
    assert client.post(f"/api/v1/companies/{other}/planned-events", json={
        "direction": "out", "amount_minor": 100, "due_date": today,
    }).status_code == 201
