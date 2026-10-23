"""Модель2.0 проходит настоящее HTTP/worker/JSONB-хранилище без выдуманного нуля риска."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.models import ForecastPoint, ForecastRun
from app.modules.forecasting.service import get_forecast_service
from tests.test_integration import _run_worker_until_idle, logged_in

GUARDED = "seasonal-guarded-2.0-w84"
LEGACY = "seasonal-block-bootstrap-1.0-w84"


@pytest.fixture
def guarded_context(client, session_factory, monkeypatch):
    from app.api.v1 import forecasts

    context = logged_in.__wrapped__(client, session_factory)
    # Меняем только выбор enqueue в изолированном тесте; продуктовый default не трогаем.
    monkeypatch.setattr(forecasts, "get_forecast_service", lambda: get_forecast_service(GUARDED))
    today = datetime.now(UTC).date()
    balance = 1000000
    lines = ["date,amount,inn,purpose,op_id,balance"]
    for offset in range(84, -1, -1):
        day = today - timedelta(days=offset)
        balance += 5000
        lines.append(f"{day},50.00,7701,Выручка,in{offset},{balance / 100:.2f}")
        if offset % 7 == 0:
            balance -= 10000
            lines.append(f"{day},-100.00,7702,Аренда,rent{offset},{balance / 100:.2f}")
    mapping = {"date": "date", "amount": "amount", "counterparty_ref": "inn",
               "purpose": "purpose", "external_id": "op_id", "balance": "balance"}
    preview = client.post(f"/api/v1/companies/{context['company_id']}/imports",
                          data={"account_id": context["account_id"], "mapping": json.dumps(mapping)},
                          files={"file": ("guarded.csv", "\n".join(lines), "text/csv")})
    assert preview.status_code == 200 and preview.json()["error_count"] == 0, preview.text
    committed = client.post(f"/api/v1/imports/{preview.json()['import_id']}/commit")
    assert committed.status_code == 200, committed.text
    event = client.post(f"/api/v1/companies/{context['company_id']}/planned-events", json={
        "account_id": context["account_id"], "direction": "in", "amount_minor": 123456,
        "due_date": str(today + timedelta(days=5)), "counterparty_name": "Отдельный заказчик",
    })
    assert event.status_code == 201, event.text
    return {**context, "as_of": today, "event_id": event.json()["id"]}


def _enqueue(client, context):
    accepted = client.post(f"/api/v1/companies/{context['company_id']}/forecasts", json={
        "account_id": context["account_id"], "as_of": str(context["as_of"]), "horizon_days": 30,
    })
    assert accepted.status_code == 202, accepted.text
    return accepted.json()


def _assert_unknown_probability(output):
    assert output["status"] == "succeeded" and output["model_version"] == GUARDED
    assert output["risk"]["available"] is False
    assert output["risk"]["probability_any_negative"] is None
    assert len(output["points"]) == 30
    assert all(point["probability_negative"] is None for point in output["points"])


def test_guarded_enqueue_is_pinned_and_null_probability_survives_storage(
    client, session_factory, guarded_context, monkeypatch,
):
    from app.api.v1 import forecasts

    accepted = _enqueue(client, guarded_context)
    assert _enqueue(client, guarded_context) == accepted
    # Пока задание ожидает, default снова legacy. Worker обязан исполнить закреплённую2.0.
    monkeypatch.setattr(forecasts, "get_forecast_service", lambda: get_forecast_service(LEGACY))
    _run_worker_until_idle(session_factory)
    output = client.get(f"/api/v1/forecasts/{accepted['forecast_run_id']}").json()
    _assert_unknown_probability(output)
    with session_factory() as session:
        run = session.get(ForecastRun, accepted["forecast_run_id"])
        assert run.probability_any_negative is None and run.risk_available is False
        assert run.details["risk_probability"]["status"] == "unavailable"
        assert session.scalars(select(ForecastPoint).where(
            ForecastPoint.forecast_run_id == run.id,
        )).all()
        assert all(point.probability_negative is None for point in session.scalars(
            select(ForecastPoint).where(ForecastPoint.forecast_run_id == run.id),
        ))
    legacy = _enqueue(client, guarded_context)
    assert legacy["forecast_run_id"] != accepted["forecast_run_id"]
    _run_worker_until_idle(session_factory)
    assert client.get(f"/api/v1/forecasts/{legacy['forecast_run_id']}").json()["model_version"] == LEGACY
    assert client.get(f"/api/v1/forecasts/{accepted['forecast_run_id']}").json() == output


def test_guarded_all_four_scenarios_preserve_base_and_unknown_risk(
    client, session_factory, guarded_context, monkeypatch,
):
    from app.api.v1 import forecasts

    accepted = _enqueue(client, guarded_context)
    _run_worker_until_idle(session_factory)
    base_id = accepted["forecast_run_id"]
    base = client.get(f"/api/v1/forecasts/{base_id}").json()
    _assert_unknown_probability(base)
    # Сценарии от2.0 не должны переключиться на новый default enqueue.
    monkeypatch.setattr(forecasts, "get_forecast_service", lambda: get_forecast_service(LEGACY))
    changes = [
        {"kind": "add_expense", "amount_minor": 2000000,
         "on_date": str(guarded_context["as_of"] + timedelta(days=3))},
        {"kind": "delay_event", "target_id": guarded_context["event_id"], "shift_days": 7},
        {"kind": "reduce_irregular_inflow", "factor": 0.5},
        {"kind": "increase_recurring", "factor": 1.5},
    ]
    for change in changes:
        scenario = client.post(f"/api/v1/forecasts/{base_id}/scenarios", json={"changes": [change]})
        assert scenario.status_code == 202, scenario.text
        scenario_id = scenario.json()["forecast_run_id"]
        _run_worker_until_idle(session_factory)
        output = client.get(f"/api/v1/forecasts/{scenario_id}").json()
        _assert_unknown_probability(output)
        comparison = client.get(f"/api/v1/forecasts/{scenario_id}/comparison")
        assert comparison.status_code == 200, comparison.text
        compared = comparison.json()
        assert compared["model_version"] == GUARDED and len(compared["points"]) == 30
        assert compared["risk"]["base"]["probability_any_negative"] is None
        assert compared["risk"]["scenario"]["probability_any_negative"] is None
        assert any(point["delta_balance_minor"] != 0 for point in compared["points"])
        if change["kind"] == "add_expense":
            assert compared["points"][-1]["delta_balance_minor"] == -2000000
            assert output["risk"]["first_negative_date"] is not None
            assert output["risk"]["max_deficit_minor"] > 0
        explanations = client.get(f"/api/v1/forecasts/{scenario_id}/explanations")
        assert explanations.status_code == 200 and explanations.json()["available"] is True
    assert client.get(f"/api/v1/forecasts/{base_id}").json() == base
