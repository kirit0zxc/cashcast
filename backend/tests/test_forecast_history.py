"""История читает сохранённые расчёты, не запускает новые и не раскрывает снимки."""

import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, func, select

from app.core.models import ForecastRun, Job
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _runs(session_factory, company, account, count=5, start=1000):
    ids = []
    with session_factory.begin() as session:
        for index in range(count):
            run_id = uuid.UUID(int=start + index)
            session.add(ForecastRun(
                id=run_id, company_id=uuid.UUID(company), account_id=uuid.UUID(account),
                as_of=date(2026, 9, 30), horizon_days=30, data_version=f"history-{start}-{index}",
                model_version="seasonal-block-bootstrap-1.0-w84", seed=42, status="pending",
                created_at=datetime(2026, 10, 23, 12, tzinfo=UTC) + timedelta(seconds=index // 3),
                input_snapshot={"private": "RAW-SOURCE-MUST-NOT-LEAK"},
            ))
            ids.append(str(run_id))
    return ids


def _get(client, context, **params):
    company, _, account, _ = context
    return client.get(f"/api/v1/companies/{company}/forecasts", params={"account_id": account, **params})


def test_history_keyset_visits_ties_without_duplicates_when_new_run_arrives(
    client, context, session_factory,
):
    company, _, account, _ = context
    ids = _runs(session_factory, company, account, count=7)
    page = _get(client, context, limit=2)
    assert page.status_code == 200, page.text
    seen = [item["id"] for item in page.json()["items"]]
    cursor = page.json()["next_cursor"]
    assert seen == list(reversed(ids))[:2] and cursor
    # Запись после первой страницы не сдвигает границу предыдущих результатов.
    new_id = _runs(session_factory, company, account, count=1, start=9999)[0]
    with session_factory.begin() as session:
        session.get(ForecastRun, new_id).created_at = datetime.now(UTC)
    while cursor:
        page = _get(client, context, limit=2, cursor=cursor)
        assert page.status_code == 200, page.text
        seen.extend(item["id"] for item in page.json()["items"])
        cursor = page.json()["next_cursor"]
    assert seen == list(reversed(ids)) and len(set(seen)) == 7
    assert _get(client, context, limit=1).json()["items"][0]["id"] == new_id


def test_history_returns_owned_saved_metadata_and_nullable_legacy_job_without_enqueue(
    client, context, session_factory, monkeypatch,
):
    from app.modules.jobs import queue

    company, other, account, beta = context
    base, scenario = _runs(session_factory, company, account, count=2)
    _runs(session_factory, company, beta, count=1, start=2000)
    with session_factory.begin() as session:
        run = session.get(ForecastRun, scenario)
        run.base_forecast_id = uuid.UUID(base)
        run.data_version = session.get(ForecastRun, base).data_version
        run.scenario_hash = "scenario-test"
        run.status = "failed"
        run.error_code = "forecast_resource_limit"
        job = Job(kind="forecast", company_id=uuid.UUID(company),
                  dedupe_key=f"forecast:{scenario}", payload={"forecast_run_id": scenario,
                  "private": "RAW-SOURCE-MUST-NOT-LEAK"})
        session.add(job)
        session.flush()
        job_id = str(job.id)
        # Чужой job с подходящим ключом не должен утечь через историю legacy run.
        session.add(Job(kind="forecast", company_id=uuid.UUID(other),
                        dedupe_key=f"forecast:{base}", payload={"forecast_run_id": base}))
        session.flush()
        counts = (session.scalar(select(func.count()).select_from(ForecastRun)),
                  session.scalar(select(func.count()).select_from(Job)))

    def forbidden_enqueue(*args, **kwargs):
        raise AssertionError("Чтение истории не должно создавать задания")

    monkeypatch.setattr(queue, "enqueue", forbidden_enqueue)
    response = _get(client, context)
    assert response.status_code == 200, response.text
    assert "RAW-SOURCE-MUST-NOT-LEAK" not in response.text
    items = {item["id"]: item for item in response.json()["items"]}
    assert set(items) == {base, scenario}
    assert items[base]["job_id"] is None and items[base]["base_forecast_id"] is None
    assert items[scenario]["job_id"] == job_id and items[scenario]["base_forecast_id"] == base
    assert items[scenario]["error_code"] == "forecast_resource_limit"
    assert items[scenario]["status"] == "failed" and items[scenario]["seed"] == 42
    assert set(items[scenario]) == {"id", "account_id", "as_of", "horizon_days", "status",
                                   "model_version", "data_version", "seed", "base_forecast_id",
                                   "created_at", "error_code", "job_id"}
    assert items[scenario]["created_at"].startswith("2026-10-23T12:00:00")
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ForecastRun)) == counts[0]
        assert session.scalar(select(func.count()).select_from(Job)) == counts[1]


def test_history_requires_session_and_owned_company_account(client, context, session_factory):
    company, other, account, beta = context
    _runs(session_factory, company, beta, count=1)
    assert _get(client, context).json() == {"items": [], "next_cursor": None}
    assert client.get(f"/api/v1/companies/{other}/forecasts", params={"account_id": account}).status_code == 404
    assert _get(client, context, account_id=str(uuid.uuid4())).status_code == 404
    assert client.get(f"/api/v1/companies/{company}/forecasts").status_code == 422
    client.cookies.clear()
    assert _get(client, context).status_code == 401


def test_history_sql_projects_metadata_without_loading_input_or_result_json(
    client, context, session_factory, engine,
):
    company, _, account, _ = context
    _runs(session_factory, company, account, count=3)
    statements = []

    def capture(connection, cursor, statement, parameters, execution_context, executemany):
        if statement.startswith("SELECT forecast_run."):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = _get(client, context, limit=100)
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == 3
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "input_snapshot" not in statements[0] and "details" not in statements[0]


@pytest.mark.parametrize("cursor", ["", "not-base64", "a" * 5000,
    base64.urlsafe_b64encode(b"[]").decode(), base64.urlsafe_b64encode(b"true").decode(),
    base64.urlsafe_b64encode(json.dumps({"v": 1, "id": "bad"}).encode()).decode()])
def test_history_rejects_invalid_cursor_safely(client, context, cursor):
    response = _get(client, context, cursor=cursor)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_history_cursor_is_bound_to_account(client, context, session_factory):
    company, _, account, beta = context
    _runs(session_factory, company, account, count=2)
    cursor = _get(client, context, limit=1).json()["next_cursor"]
    assert cursor
    response = _get(client, context, account_id=beta, cursor=cursor)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.parametrize("changes", [
    {"created_at": "2026-10-23"}, {"created_at": "bad"},
    {"created_at": "0001-01-01T00:00:00+23:59"}, {"id": "bad"},
    {"v": True}, {"extra": 0}, {"company_id": str(uuid.UUID(int=999))},
])
def test_history_rejects_tampered_cursor_fields(client, context, session_factory, changes):
    company, _, account, _ = context
    _runs(session_factory, company, account, count=2)
    cursor = _get(client, context, limit=1).json()["next_cursor"]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    payload.update(changes)
    altered = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    response = _get(client, context, cursor=altered)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.parametrize("limit", [0, 101, "bad"])
def test_history_rejects_unsupported_page_size(client, context, limit):
    assert _get(client, context, limit=limit).status_code == 422
