"""Прогноз и сценарий используют вход enqueue, даже если БД изменилась до worker."""

import json
from datetime import date

import pytest
from sqlalchemy import select

from app.core.forecast_input import ForecastInputCodec
from app.core.models import BankTransaction, DailyBalance, ForecastRun, Job
from tests.test_integration import (
    _run_worker_until_idle,
    _statement_csv,
    logged_in,
)


@pytest.fixture
def frozen_context(client, session_factory):
    # Повторно используем подготовку контекста; fixture не вызывается как pytest-объект.
    return logged_in.__wrapped__(client, session_factory)


def test_enqueue_freezes_inputs_and_scenario_keeps_original_base(client, session_factory, frozen_context):
    company, account = frozen_context["company_id"], frozen_context["account_id"]
    mapping = {"date": "date", "amount": "amount", "balance": "balance", "external_id": "op_id"}
    preview = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps(mapping),
    }, files={"file": ("frozen.csv", _statement_csv(date(2026, 3, 1)), "text/csv")}).json()
    assert client.post(f"/api/v1/imports/{preview['import_id']}/commit").status_code == 200
    request = {"account_id": account, "as_of": "2026-03-01", "horizon_days": 30}
    base = client.post(f"/api/v1/companies/{company}/forecasts", json=request).json()
    with session_factory() as session:
        original = session.get(ForecastRun, base["forecast_run_id"]).input_snapshot
        assert ForecastInputCodec.encode(ForecastInputCodec.decode(original))["input"] == original["input"]
        # Между enqueue и worker пользователь исправил импортированный остаток/операцию.
        balance = session.scalars(select(DailyBalance).order_by(DailyBalance.balance_date.desc())).first()
        balance.closing_balance_minor += 99999999
        session.scalars(select(BankTransaction)).first().amount_minor += 5555555
        session.commit()
    pending_scenario = client.post(f"/api/v1/forecasts/{base['forecast_run_id']}/scenarios",
                                  json={"changes": [{"kind": "add_expense", "amount_minor": 100000,
                                                      "on_date": "2026-03-05"}]})
    assert pending_scenario.status_code == 409
    _run_worker_until_idle(session_factory)
    base_out = client.get(f"/api/v1/forecasts/{base['forecast_run_id']}").json()
    assert base_out["opening_balance_minor"] == original["input"]["opening_balance_minor"]
    scenario = client.post(f"/api/v1/forecasts/{base['forecast_run_id']}/scenarios", json={
        "changes": [{"kind": "add_expense", "amount_minor": 100000, "on_date": "2026-03-05"}],
    })
    assert scenario.status_code == 202, scenario.text
    scenario_id = scenario.json()["forecast_run_id"]
    with session_factory() as session:
        frozen = session.get(ForecastRun, scenario_id).input_snapshot
        assert frozen["input"]["txns"] == original["input"]["txns"]
        assert frozen["input"]["daily_balances"] == original["input"]["daily_balances"]
        assert frozen["input"]["scenario"][0]["amount_minor"] == 100000
    _run_worker_until_idle(session_factory)
    output = client.get(f"/api/v1/forecasts/{scenario_id}").json()
    assert output["status"] == "succeeded"
    nested = client.post(f"/api/v1/forecasts/{scenario_id}/scenarios", json={
        "changes": [{"kind": "add_expense", "amount_minor": 100000, "on_date": "2026-03-05"}],
    })
    assert nested.status_code == 409
    assert nested.json()["error"]["code"] == "nested_scenario_not_supported"
    assert output["opening_balance_minor"] == base_out["opening_balance_minor"]
    assert output["points"][-1]["balance_p50_minor"] == base_out["points"][-1]["balance_p50_minor"] - 100000
    explanations = client.get(f"/api/v1/forecasts/{scenario_id}/explanations").json()
    assert explanations["available"] is True
    assert explanations["items"]
    comparison = client.get(f"/api/v1/forecasts/{scenario_id}/comparison")
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["base_forecast_id"] == base["forecast_run_id"]
    assert len(comparison.json()["points"]) == 30
    assert comparison.json()["points"][-1]["delta_balance_minor"] == -100000
    for change in [{"kind": "add_expense"}, {"kind": "delay_event", "target_id": "missing", "shift_days": 1},
                   {"kind": "reduce_irregular_inflow", "factor": 1.5},
                   {"kind": "increase_recurring", "factor": 0.5}]:
        assert client.post(f"/api/v1/forecasts/{base['forecast_run_id']}/scenarios",
                           json={"changes": [change]}).status_code == 422
    assert client.get(f"/api/v1/forecasts/{base['forecast_run_id']}/comparison").status_code == 409
    # Другой seed нарушает парное сравнение; API сообщает это явно.
    unpaired = client.post(f"/api/v1/forecasts/{base['forecast_run_id']}/scenarios", json={
        "changes": [{"kind": "add_expense", "amount_minor": 100000, "on_date": "2026-03-05"}], "seed": 99,
    }).json()
    _run_worker_until_idle(session_factory)
    assert client.get(f"/api/v1/forecasts/{unpaired['forecast_run_id']}/comparison").status_code == 409
    # Новый базовый запрос, напротив, видит исправленные входы и имеет новую версию.
    updated = client.post(f"/api/v1/companies/{company}/forecasts", json=request).json()
    assert updated["forecast_run_id"] != base["forecast_run_id"]


def test_worker_keeps_queued_model_when_default_factory_changes(client, session_factory, frozen_context, monkeypatch):
    from app.modules.jobs import handlers

    accepted = client.post(f"/api/v1/companies/{frozen_context['company_id']}/forecasts", json={
        "account_id": frozen_context["account_id"], "as_of": "2026-03-01", "horizon_days": 30,
    }).json()
    real_factory = handlers.get_forecast_service

    def changed_default(model_version=None):
        return real_factory(model_version if model_version is not None else "seasonal-block-bootstrap-1.0-w28")

    # Очередь уже закрепила w84, а default теперь другой: worker обязан передать точную версию.
    monkeypatch.setattr(handlers, "get_forecast_service", changed_default)
    _run_worker_until_idle(session_factory)
    result = client.get("/api/v1/forecasts/" + accepted["forecast_run_id"]).json()
    assert result["status"] == "succeeded" and result["model_version"] == "seasonal-block-bootstrap-1.0-w84"


def test_unknown_pinned_model_fails_explicitly_without_default_fallback(client, session_factory, frozen_context):
    accepted = client.post(f"/api/v1/companies/{frozen_context['company_id']}/forecasts", json={
        "account_id": frozen_context["account_id"], "as_of": "2026-03-01", "horizon_days": 30,
    }).json()
    with session_factory() as session:
        session.get(ForecastRun, accepted["forecast_run_id"]).model_version = "unknown-model"
        session.get(Job, accepted["job_id"]).max_attempts = 1
        session.commit()
    _run_worker_until_idle(session_factory)
    job = client.get("/api/v1/jobs/" + accepted["job_id"]).json()
    result = client.get("/api/v1/forecasts/" + accepted["forecast_run_id"]).json()
    assert job["status"] == result["status"] == "failed"
    assert job["error_code"] == "unsupported_model_version" and result["points"] == []
