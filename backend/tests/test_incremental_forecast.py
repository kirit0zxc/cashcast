"""Реальный API → worker → JSONB checkpoint: новый план, неизменный старый снимок, fallback."""

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.forecast_input import ForecastInputCodec
from app.core.models import BankTransaction, ForecastRun
from app.modules.forecasting.v2.service import GuardedForecastService
from app.modules.jobs.incremental import ForecastCheckpointRepository
from tests.factories import make_account, make_company
from tests.test_integration import _run_worker_until_idle, _statement_csv, logged_in


@pytest.fixture
def context(client, session_factory):
    return logged_in.__wrapped__(client, session_factory)


def test_api_plan_update_reuses_committed_state_and_import_change_requires_full(client, session_factory, context):
    company, account = context["company_id"], context["account_id"]
    today = datetime.now(UTC).date()
    preview = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account,
        "mapping": json.dumps({"date": "date", "amount": "amount", "balance": "balance", "external_id": "op_id"}),
    }, files={"file": ("incremental.csv", _statement_csv(today), "text/csv")}).json()
    assert client.post(f"/api/v1/imports/{preview['import_id']}/commit").status_code == 200
    request = {"account_id": account, "as_of": today.isoformat(), "horizon_days": 30}

    def enqueue():
        response = client.post(f"/api/v1/companies/{company}/forecasts", json=request)
        assert response.status_code == 202, response.text
        return response.json()["forecast_run_id"]

    def output(run_id):
        response = client.get(f"/api/v1/forecasts/{run_id}")
        assert response.status_code == 200, response.text
        return response.json()

    base_id = enqueue()
    _run_worker_until_idle(session_factory)
    base = output(base_id)
    assert base["status"] == "succeeded"
    assert base["calculation"]["mode"] == "full"
    plan = client.post(f"/api/v1/companies/{company}/planned-events", json={
        "account_id": account, "direction": "out", "amount_minor": 1234567,
        "due_date": (today + timedelta(days=4)).isoformat(), "kind": "invoice",
        "counterparty_ref": "incremental-unique",
    })
    assert plan.status_code == 201, plan.text
    changed_id = enqueue()
    assert changed_id != base_id
    # Новый worker/Session восстанавливает checkpoint из PostgreSQL, не из process cache.
    with patch("app.modules.forecasting.v2.incremental_engine.random.Random", side_effect=AssertionError("bootstrap")):
        _run_worker_until_idle(session_factory)
    changed = output(changed_id)
    assert changed["status"] == "succeeded"
    assert changed["calculation"] == {
        "mode": "incremental", "reason": "planned_events_changed", "reused_history": True,
        "bootstrap_paths_generated": 0, "source_forecast_id": base_id,
    }
    assert "_incremental_state" not in json.dumps(changed)
    assert changed["points"][-1]["balance_p50_minor"] == base["points"][-1]["balance_p50_minor"] - 1234567
    assert output(base_id) == base
    with session_factory() as session:
        frozen = session.get(ForecastRun, changed_id).input_snapshot
        full = GuardedForecastService().run(ForecastInputCodec.decode(frozen))
        expected = json.loads(json.dumps([asdict(p) for p in full.points], default=str))
        assert changed["points"] == expected
        txn = session.scalars(select(BankTransaction)).first()
        txn.amount_minor += 1
        session.commit()
    new_history_id = enqueue()
    _run_worker_until_idle(session_factory)
    assert output(new_history_id)["calculation"]["mode"] == "full"
    assert output(new_history_id)["calculation"]["source_forecast_id"] is None
    # Идемпотентность не выдаётся за новое инкрементальное выполнение.
    assert enqueue() == new_history_id


@pytest.mark.parametrize("foreign_field", ["account_id", "company_id"])
def test_repository_does_not_reuse_checkpoint_across_account_or_tenant(
    client, session_factory, context, foreign_field,
):
    # Даже при совпадающем содержимом checkpoint идентичность SQL-строки обязательна.
    accepted = client.post(f"/api/v1/companies/{context['company_id']}/forecasts", json={
        "account_id": context["account_id"], "as_of": "2026-03-01", "horizon_days": 30,
    }).json()
    _run_worker_until_idle(session_factory)
    with session_factory() as session:
        base = session.get(ForecastRun, accepted["forecast_run_id"])
        data = ForecastInputCodec.decode(base.input_snapshot)
        run = ForecastRun(
            company_id=base.company_id, account_id=base.account_id, as_of=base.as_of,
            horizon_days=base.horizon_days, model_version=base.model_version,
            seed=base.seed, data_version="new-input", scenario_hash="", status="pending",
        )
        session.add(run)
        session.flush()
        repo = ForecastCheckpointRepository(session)
        assert repo.find(run, data)[1] == str(base.id)
        company = make_company(session, "Other tenant")
        account = make_account(session, company)
        setattr(base, foreign_field, account.id if foreign_field == "account_id" else company.id)
        session.flush()
        assert repo.find(run, data) == (None, None)
