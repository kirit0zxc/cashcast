"""Реальные CSV → PostgreSQL → прогноз/план-факт; повторы, конфликты и изоляция."""

import csv
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.models import ObligationImport, PlannedEvent
from app.modules.forecasting.snapshot import build_snapshot
from app.modules.imports.obligations import ObligationImportService
from tests.test_accounts import account_context
from tests.test_plan_fact_api import _payment

HEADER = ["id", "counterparty_ref", "direction", "amount", "currency", "due_date",
          "available_at", "kind", "provenance", "tax_regime"]


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _csv(*rows):
    today = datetime.now(UTC).date().isoformat()
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, HEADER, delimiter=";")
    writer.writeheader()
    for row in rows:
        writer.writerow({"id": "invoice-1", "counterparty_ref": "00123", "direction": "out",
                         "amount": "150.00", "currency": "RUB", "due_date": today,
                         "available_at": today, "kind": "invoice", "provenance": "Договор №1",
                         "tax_regime": "", **row})
    return stream.getvalue().encode("utf-8-sig")


def _preview(client, company, account, content, **data):
    return client.post(f"/api/v1/companies/{company}/obligation-imports", data={
        "account_id": account, "source_name": "invoices", **data,
    }, files={"file": ("invoices.csv", content, "text/csv")})


def _commit(client, preview):
    assert preview.status_code == 200, preview.text
    return client.post(f"/api/v1/obligation-imports/{preview.json()['import_id']}/commit")


def test_csv_commit_enters_snapshot_and_matches_fact_by_leading_zero_inn(client, context, session_factory):
    company, _, account, _ = context
    preview = _preview(client, company, account, _csv({}))
    assert preview.status_code == 200, preview.text
    assert (preview.json()["total_rows"], preview.json()["valid_count"], preview.json()["error_count"]) == (1, 1, 0)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEvent)) == 0
    result = _commit(client, preview)
    assert result.status_code == 200, result.text
    assert (result.json()["inserted"], result.json()["skipped_existing"]) == (1, 0)
    today = datetime.now(UTC).date()
    with session_factory() as session:
        event = session.scalar(select(PlannedEvent))
        assert event.source_ref == f"{account}:invoices:invoice-1"
        assert event.provenance == "Договор №1" and event.tax_regime is None
        assert event.counterparty_ref == "00123"
        assert isinstance(event.id, uuid.UUID)
        snap = build_snapshot(session, account_id=account, as_of=today, horizon_days=30, seed=42)
        assert snap.data.planned_events[0].counterparty_ref == "00123"
        assert snap.data.planned_events[0].remaining_amount_minor == 15000
    public = client.get(f"/api/v1/companies/{company}/planned-events").json()[0]
    assert public["counterparty_ref"] == "00123" and public["provenance"] == "Договор №1"
    assert public["tax_regime"] is None
    _payment(client, company, account, "100.00", "invoice-payment", today.isoformat())
    result = client.post(f"/api/v1/companies/{company}/plan-fact", params={
        "account_id": account, "as_of": today.isoformat(),
    })
    assert result.status_code == 200, result.text
    assert result.json()["items"][0]["event"]["remaining_amount_minor"] == 5000
    assert len(result.json()["confirmed_matches"]) == 1


def test_reimport_does_not_reset_paid_balance_or_manual_edits(client, context, session_factory):
    company, _, account, _ = context
    original = _csv({})
    preview = _preview(client, company, account, original)
    initial = _commit(client, preview)
    with session_factory() as session:
        event_id = session.scalar(select(PlannedEvent.id))
    response = client.patch(f"/api/v1/planned-events/{event_id}", json={"amount_minor": 20000, "status": "paid"})
    assert response.status_code == 200, response.text
    assert _commit(client, preview).json() == initial.json()
    repeated = _preview(client, company, account, original)
    assert repeated.json()["reused"] is True and repeated.json()["status"] == "committed"
    # Другие байты файла, но тот же нормализованный документ: пропуск без перезаписи.
    normalized = original.replace(b"\r\n", b"\n")
    another = _preview(client, company, account, normalized)
    assert another.json()["reused"] is False
    result = _commit(client, another)
    assert result.status_code == 200, result.text
    assert (result.json()["inserted"], result.json()["skipped_existing"]) == (0, 1)
    with session_factory() as session:
        event = session.get(PlannedEvent, event_id)
        assert (event.amount_minor, event.remaining_amount_minor, event.status) == (20000, 0, "paid")
        assert event.source_payload["amount_minor"] == 15000


def test_changed_source_id_rejects_entire_batch_without_overwriting_original(client, context, session_factory):
    company, _, account, _ = context
    assert _commit(client, _preview(client, company, account, _csv({}))).status_code == 200
    changed = _preview(client, company, account, _csv({"id": "new"}, {"amount": "151.00"}))
    response = _commit(client, changed)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "SOURCE_ID_CONFLICT"
    with session_factory() as session:
        events = session.scalars(select(PlannedEvent)).all()
        assert len(events) == 1 and events[0].amount_minor == 15000
        assert session.get(ObligationImport, uuid.UUID(changed.json()["import_id"])).status == "previewed"


def test_any_row_error_blocks_partial_commit_and_does_not_echo_source(client, context, session_factory):
    company, _, account, _ = context
    future = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    preview = _preview(client, company, account, _csv({}, {"id": "secret-id", "available_at": future}))
    assert preview.status_code == 200, preview.text
    assert (preview.json()["total_rows"], preview.json()["valid_count"], preview.json()["error_count"]) == (2, 1, 1)
    assert preview.json()["sample_errors"] == [{"row": 3, "field": "available_at", "code": "future_knowledge"}]
    assert "secret-id" not in preview.text
    response = _commit(client, preview)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_import"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEvent)) == 0


@pytest.mark.parametrize("identifier", ["\tinvoice", "invoice\t", "invoice\n"])
def test_control_characters_are_rejected_before_id_normalization(client, context, identifier):
    company, _, account, _ = context
    preview = _preview(client, company, account, _csv({"id": identifier}))
    assert preview.status_code == 200, preview.text
    assert preview.json()["error_count"] > 0
    assert _commit(client, preview).status_code == 422


def test_same_external_id_is_scoped_to_account_and_source(client, context, session_factory):
    company, _, account, second = context
    for selected, name in [(account, "invoices"), (second, "invoices"), (account, "other")]:
        response = _commit(client, _preview(client, company, selected, _csv({}), source_name=name))
        assert response.status_code == 200 and response.json()["inserted"] == 1
    with session_factory() as session:
        assert len(set(session.scalars(select(PlannedEvent.source_ref)))) == 3


def test_obligation_import_requires_membership_session_and_csrf(client, context, session_factory):
    company, other, account, _ = context
    from app.core.models import Account

    with session_factory() as session:
        foreign_account = str(session.scalar(select(Account.id).where(Account.company_id == uuid.UUID(other))))
    assert _preview(client, other, foreign_account, _csv({})).status_code == 404
    assert _preview(client, company, foreign_account, _csv({})).status_code == 404
    preview = _preview(client, company, account, _csv({}))
    user_id = client.get("/api/v1/auth/me").json()["id"]
    from app.core.models import CompanyMember

    with session_factory.begin() as session:
        session.delete(session.get(CompanyMember, {"company_id": uuid.UUID(company), "user_id": uuid.UUID(user_id)}))
    assert _commit(client, preview).status_code == 404
    client.headers.pop("X-CSRF-Token")
    assert _commit(client, preview).status_code == 403
    client.cookies.clear()
    assert _preview(client, company, account, _csv({})).status_code == 401
    assert _commit(client, preview).status_code == 401


@pytest.mark.parametrize("data,code", [
    ({"source_name": " "}, "invalid_source_name"),
    ({"source_name": "\tinvoices"}, "invalid_source_name"),
    ({"source_name": "\u0085invoices"}, "invalid_source_name"),
    ({"source_name": "x" * 41}, "validation_error"),
    ({"account_id": "invalid"}, "validation_error"),
    ({"as_of": "9999-01-01"}, "future_as_of"),
])
def test_invalid_obligation_request_is_422(client, context, data, code):
    company, _, account, _ = context
    response = _preview(client, company, account, _csv({}), **data) if "account_id" not in data else client.post(
        f"/api/v1/companies/{company}/obligation-imports", data={"source_name": "invoices", **data},
        files={"file": ("invoice.csv", _csv({}), "text/csv")},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


def test_non_utf8_and_oversized_upload_are_rejected(client, context):
    company, _, account, _ = context
    response = _preview(client, company, account, b"\xff\xff")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_encoding"
    assert _preview(client, company, account, b"a" * (10 * 1024 * 1024 + 1)).status_code == 413


def test_concurrent_preview_and_commit_are_idempotent(session_factory, client, context):
    company, _, account, _ = context
    user_id = client.get("/api/v1/auth/me").json()["id"]

    def preview(_):
        with session_factory.begin() as session:
            return ObligationImportService(session).preview(
                company_id=uuid.UUID(company), account_id=uuid.UUID(account), user_id=uuid.UUID(user_id),
                source_name="parallel", as_of=datetime.now(UTC).date(), content=_csv({}),
            )["import_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        imports = list(pool.map(preview, range(2)))
    assert imports[0] == imports[1]

    def commit(_):
        with session_factory.begin() as session:
            return ObligationImportService(session).commit(
                company_id=uuid.UUID(company), import_id=uuid.UUID(imports[0]),
            )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, range(2)))
    assert results[0] == results[1] and results[0]["inserted"] == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEvent)) == 1


def test_imported_past_knowledge_does_not_bypass_historical_plan_guard(client, context):
    company, _, account, _ = context
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    preview = _preview(client, company, account, _csv({"available_at": yesterday}), as_of=yesterday)
    assert _commit(client, preview).status_code == 200
    response = client.get(f"/api/v1/companies/{company}/plan-fact", params={"account_id": account, "as_of": yesterday})
    assert response.status_code == 409 and response.json()["error"]["code"] == "historical_plan_unavailable"


def test_commit_checks_capacity_with_existing_closed_events_and_identical_skips(client, context, session_factory):
    company, _, account, _ = context
    today = datetime.now(UTC).date()
    with session_factory.begin() as session:
        session.add_all([PlannedEvent(
            company_id=uuid.UUID(company), account_id=uuid.UUID(account), direction="out",
            amount_minor=1, remaining_amount_minor=0, due_date=today,
            status="paid", kind="manual", source="manual",
        ) for _ in range(1999)])
    # Нельзя принять два документа, если в модель помещается только один новый.
    too_many = _preview(client, company, account, _csv({"id": "one"}, {"id": "two"}))
    response = _commit(client, too_many)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "forecast_capacity_exceeded"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEvent)) == 1999
    accepted = _preview(client, company, account, _csv({"id": "one"}))
    assert _commit(client, accepted).status_code == 200
    # Другой файл с прежним документом не расходует ещё одно место.
    same = _preview(client, company, account, _csv({"id": "one"}).replace(b"\r\n", b"\n"))
    assert _commit(client, same).json()["skipped_existing"] == 1
    assert _commit(client, _preview(client, company, account, _csv({"id": "next"}))).status_code == 409
    manual = client.post(f"/api/v1/companies/{company}/planned-events", json={
        "account_id": account, "amount_minor": 1, "direction": "out", "due_date": today.isoformat(),
    })
    assert manual.status_code == 409 and manual.json()["error"]["code"] == "forecast_capacity_exceeded"


def test_commit_checks_combined_money_budget_before_writing(client, context, session_factory):
    company, _, account, _ = context
    maximum = _preview(client, company, account, _csv({"amount": "90000000000000.00"}))
    assert _commit(client, maximum).status_code == 200
    overflow = _preview(client, company, account, _csv({"id": "extra", "amount": "0.01"}))
    response = _commit(client, overflow)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "forecast_capacity_exceeded"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEvent)) == 1


def test_manual_patch_obeys_combined_budget_but_payment_can_release_it(client, context):
    company, _, account, _ = context
    today = datetime.now(UTC).date().isoformat()
    events = []
    for amount in (9_000_000_000_000_000 - 100, 100):
        response = client.post(f"/api/v1/companies/{company}/planned-events", json={
            "account_id": account, "amount_minor": amount, "direction": "out", "due_date": today,
        })
        assert response.status_code == 201, response.text
        events.append(response.json()["id"])
    increased = {"amount_minor": 9_000_000_000_000_000}
    response = client.patch(f"/api/v1/planned-events/{events[0]}", json=increased)
    assert response.status_code == 409 and response.json()["error"]["code"] == "forecast_capacity_exceeded"
    assert client.patch(f"/api/v1/planned-events/{events[1]}", json={"status": "paid"}).status_code == 200
    assert client.patch(f"/api/v1/planned-events/{events[0]}", json=increased).status_code == 200


def test_concurrent_distinct_imports_share_one_money_budget(client, context, session_factory):
    from app.core.errors import AppError

    company, _, account, _ = context
    imports = [_preview(client, company, account, _csv({
        "id": identifier, "amount": "90000000000000.00",
    })).json()["import_id"] for identifier in ("one", "two")]

    def commit(import_id):
        try:
            with session_factory.begin() as session:
                return ObligationImportService(session).commit(
                    company_id=uuid.UUID(company), import_id=uuid.UUID(import_id),
                )["status"]
        except AppError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, imports)) == ["committed", "forecast_capacity_exceeded"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PlannedEvent)) == 1


def test_legacy_oversized_snapshot_is_rejected_before_job_creation(client, context, session_factory):
    from app.core.models import Job

    company, _, account, _ = context
    today = datetime.now(UTC).date()
    with session_factory.begin() as session:
        session.add_all([PlannedEvent(
            company_id=uuid.UUID(company), account_id=uuid.UUID(account), direction="out",
            amount_minor=1, remaining_amount_minor=0, due_date=today,
            status="paid", kind="manual", source="manual",
        ) for _ in range(2001)])
    response = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": today.isoformat(), "horizon_days": 30,
    })
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "forecast_resource_limit"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
