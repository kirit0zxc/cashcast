"""Демо-источники → реальные планы/worker; ошибки, изоляция, повторы и provenance."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.models import BankTransaction, CompanyMember, PlannedEvent
from app.modules.external_sources.adapters import tax_template
from app.modules.jobs.worker import run_once
from tests.test_accounts import account_context
from tests.test_plan_fact_api import _payment


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _preview(client, context, provider="bank", **extra):
    company, _, account, _ = context
    return client.post(f"/api/v1/companies/{company}/external-sources/{provider}/preview",
                       json={"account_id": account, **extra})


def _tax(client, context, content=None):
    company, _, account, _ = context
    return client.post(f"/api/v1/companies/{company}/external-tax-imports", data={"account_id": account},
                       files={"file": ("taxes.csv", tax_template() if content is None else content, "text/csv")})


def _commit(client, response):
    assert response.status_code == 200, response.text
    return client.post(f"/api/v1/obligation-imports/{response.json()['import_id']}/commit")


def _count(session_factory, model):
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize("provider", ["bank", "onec"])
def test_demo_preview_requires_confirmation_and_preserves_source_categories(client, context, session_factory, provider):
    response = _preview(client, context, provider)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "demo" and body["provider_id"] == provider
    assert body["valid_count"] == 4 and not body["error_count"]
    assert len(body["documents"]) == 4
    assert _count(session_factory, PlannedEvent) == _count(session_factory, BankTransaction) == 0
    assert all("ДЕМО" in doc["provenance"] for doc in body["documents"])
    committed = _commit(client, response)
    assert committed.status_code == 200 and committed.json()["inserted"] == 4
    with session_factory() as session:
        events = session.scalars(select(PlannedEvent)).all()
        assert all(e.source == "csv" and e.account_id == uuid.UUID(context[2]) for e in events)
        assert all(e.source_payload["external_mode"] == "demo" for e in events)
        assert all(e.category is not None for e in events)
        assert {e.source_payload["document_kind"] for e in events} == (
            {"loan_schedule", "payroll", "payment_order"} if provider == "bank"
            else {"customer_invoice", "supplier_invoice", "contract_installment"})
    assert _count(session_factory, BankTransaction) == 0


def test_repeated_source_does_not_reopen_cancelled_or_reset_partly_paid_events(client, context, session_factory):
    first = _preview(client, context)
    assert _commit(client, first).status_code == 200
    with session_factory.begin() as session:
        events = session.scalars(select(PlannedEvent).order_by(PlannedEvent.id)).all()
        events[0].status, events[0].remaining_amount_minor = "cancelled", 0
        events[1].status, events[1].remaining_amount_minor = "partially_paid", 123
        saved = [(e.id, e.status, e.remaining_amount_minor, e.source_payload) for e in events]
    repeated = _preview(client, context)
    assert repeated.json()["reused"] and repeated.json()["status"] == "committed"
    assert _commit(client, repeated).status_code == 200
    with session_factory() as session:
        assert [(e.id, e.status, e.remaining_amount_minor, e.source_payload)
                for e in session.scalars(select(PlannedEvent).order_by(PlannedEvent.id))] == saved


def test_tax_template_paid_rows_and_real_snapshot(client, context, session_factory):
    template = client.get(f"/api/v1/companies/{context[0]}/external-tax-template")
    assert template.status_code == 200 and template.content == tax_template()
    assert "attachment" in template.headers["content-disposition"]
    response = _tax(client, context)
    assert response.status_code == 200, response.text
    assert response.json()["skipped_settled"] == 1
    assert response.json()["valid_count"] == 2
    assert _commit(client, response).json()["inserted"] == 2
    with session_factory() as session:
        events = session.scalars(select(PlannedEvent)).all()
        assert {e.kind for e in events} == {"tax"}
        assert {e.category for e in events} == {"tax"}
        assert {e.tax_regime for e in events} == {"УСН", "ОСНО"}
        assert sum(e.amount_minor for e in events) == 6_000_000
        assert not any("paid-2026" in e.source_ref for e in events)


@pytest.mark.parametrize("amount", ["NaN", "1e5", "-10.00", "0.00", "12.345", "90000000000000.01"])
def test_invalid_tax_amount_blocks_entire_import_without_echo(client, context, session_factory, amount):
    content = tax_template().replace(b"42000.00", amount.encode())
    preview = _tax(client, context, content)
    assert preview.status_code == 200 and preview.json()["error_count"] > 0
    assert _commit(client, preview).status_code == 422
    assert _count(session_factory, PlannedEvent) == 0
    assert amount not in str(preview.json()["sample_errors"])


def test_tax_error_reports_original_line_after_skipping_paid_rows(client, context):
    header, first, second, paid = tax_template().decode("utf-8-sig").splitlines()
    content = ("\n".join([header, paid, first.replace("42000.00", "bad"), second]) + "\n").encode()
    preview = _tax(client, context, content)
    assert preview.json()["sample_errors"] == [{"row": 3, "field": "amount", "code": "invalid_decimal_amount"}]


def test_all_paid_tax_file_is_valid_noop_and_repeated_preview_stays_valid(client, context, session_factory):
    content = tax_template().replace(b";due\n", b";paid\n")
    for _ in range(2):
        response = _tax(client, context, content)
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["valid_count"], body["error_count"], body["skipped_settled"]) == (0, 0, 3)
        assert body["total_rows"] == 0
        assert body["documents"] == body["sample_errors"] == []
    assert _count(session_factory, PlannedEvent) == 0


def test_changed_document_conflicts_atomically_and_keeps_original(client, context, session_factory):
    assert _commit(client, _tax(client, context)).status_code == 200
    changed = tax_template().replace(b"42000.00", b"42001.00").replace(b"tax-vat-2026-q3-1", b"new-tax")
    response = _commit(client, _tax(client, context, changed))
    assert response.status_code == 409 and response.json()["error"]["code"] == "SOURCE_ID_CONFLICT"
    assert _count(session_factory, PlannedEvent) == 2


@pytest.mark.parametrize("content,code", [
    (b"%PDF-1.4", "invalid_tax_format"),
    (b"\xff\xff", "invalid_tax_format"),
    (b"id;tax_name;amount;due_date;available_at;tax_regime;status\n", "empty_tax_file"),
    (tax_template().replace(b";due\n", b";unknown\n"), "invalid_tax_status"),
    (tax_template().replace(b"tax-vat-2026-q3-1", b"tax-usn-2026-q3"), "invalid_tax_id"),
    (tax_template().replace(b"42000.00", b"42000.00\x00"), "invalid_tax_row"),
])
def test_malformed_or_unsupported_tax_file_is_rejected(client, context, session_factory, content, code):
    response = _tax(client, context, content)
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert _count(session_factory, PlannedEvent) == 0


def test_future_knowledge_and_oversized_upload_are_rejected(client, context, session_factory):
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat().encode()
    preview = _tax(client, context, tax_template().replace(b"2026-10-24", tomorrow))
    assert preview.status_code == 200
    assert any(e["code"] == "future_knowledge" for e in preview.json()["sample_errors"])
    assert _commit(client, preview).status_code == 422
    assert _tax(client, context, b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert _count(session_factory, PlannedEvent) == 0


def test_source_preview_is_scoped_by_company_account_csrf_and_readonly_role(client, context, session_factory):
    company, foreign, account, second = context
    assert client.get(f"/api/v1/companies/{foreign}/external-sources").status_code == 404
    assert client.post(f"/api/v1/companies/{foreign}/external-sources/bank/preview",
                       json={"account_id": account}).status_code == 404
    preview = _preview(client, context)
    assert _commit(client, preview).status_code == 200
    other_account = client.post(f"/api/v1/companies/{company}/external-sources/bank/preview",
                                json={"account_id": second})
    assert _commit(client, other_account).json()["inserted"] == 4
    assert _count(session_factory, PlannedEvent) == 8
    user_id = client.get("/api/v1/auth/me").json()["id"]
    with session_factory.begin() as session:
        session.get(CompanyMember, {"company_id": uuid.UUID(company), "user_id": uuid.UUID(user_id)}).role = "viewer"
    assert client.get(f"/api/v1/companies/{company}/external-sources").status_code == 200
    assert _preview(client, context).status_code == 403
    assert _tax(client, context).status_code == 403
    assert _commit(client, preview).status_code == 403
    client.headers.pop("X-CSRF-Token")
    assert _preview(client, context).json()["error"]["code"] == "csrf_failed"
    client.cookies.clear()
    assert _preview(client, context).status_code == 401


def test_external_sources_change_real_worker_forecast_but_keep_old_result(client, context, session_factory):
    company, _, account, _ = context
    today = datetime.now(UTC).date().isoformat()
    _payment(client, company, account, "100.00", "initial", today)

    def forecast():
        response = client.post(f"/api/v1/companies/{company}/forecasts", json={
            "account_id": account, "as_of": today, "horizon_days": 30,
        })
        assert response.status_code == 202, response.text
        for _ in range(5):
            if not run_once(session_factory, worker_id="external-source-test", lease_seconds=30):
                break
        result = client.get(f"/api/v1/forecasts/{response.json()['forecast_run_id']}")
        assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
        return result.json()

    before = forecast()
    assert _commit(client, _preview(client, context)).status_code == 200
    after = forecast()
    assert after["id"] != before["id"] and after["data_version"] != before["data_version"]
    assert before["points"][-1]["balance_p50_minor"] - after["points"][-1]["balance_p50_minor"] == 33_500_000
    assert client.get(f"/api/v1/forecasts/{before['id']}").json() == before
