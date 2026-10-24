"""Новый default, старые задания, сценарий и карточка проходят реальный API/worker/БД."""

from datetime import timedelta

from app.modules.forecasting.service import get_forecast_service
from app.modules.forecasting.v2.estimated import MODEL_VERSION
from tests.test_guarded_model_api import _enqueue, guarded_context
from tests.test_integration import _run_worker_until_idle


def test_probability_roundtrip_and_pinned_previous_version(client, session_factory, monkeypatch):
    from app.api.v1 import forecasts

    context = guarded_context.__wrapped__(client, session_factory, monkeypatch)
    old = _enqueue(client, context)
    monkeypatch.setattr(forecasts, "get_forecast_service", lambda: get_forecast_service(MODEL_VERSION))
    current = _enqueue(client, context)
    assert old["forecast_run_id"] != current["forecast_run_id"]
    _run_worker_until_idle(session_factory)
    old_result = client.get(f"/api/v1/forecasts/{old['forecast_run_id']}").json()
    path = f"/api/v1/forecasts/{current['forecast_run_id']}"
    result = client.get(path).json()
    assert old_result["model_version"] == "seasonal-guarded-2.0-w84"
    assert old_result["risk"]["probability_any_negative"] is None
    assert result["model_version"] == MODEL_VERSION and result["status"] == "succeeded"
    assert result["risk"]["available"] is True
    assert result["risk"]["probability_status"] == "estimated_uncalibrated"
    assert result["risk"]["probability_calibrated"] is False
    assert all(0 <= p["probability_negative"] <= 1 for p in result["points"])
    gap = client.get(path + "/cash-gaps").json()
    assert gap["probability"] == result["risk"]["probability_any_negative"]
    assert gap["probability_status"] == "estimated_uncalibrated"
    assert "не откалибрована" in gap["probability_reason"]
    preview = client.post(path + "/cash-gap-preview", json={"actions": [{
        "kind": "financing", "date": str(context["as_of"] + timedelta(days=1)),
        "amount_minor": 10000, "repayment_date": str(context["as_of"] + timedelta(days=31)), "cost_minor": 0,
    }]}).json()
    assert preview["probability"] is None
    assert preview["probability_status"] == "unavailable"
    scenario = client.post(path + "/scenarios", json={"changes": [{
        "kind": "add_expense", "amount_minor": 1000000000,
        "on_date": str(context["as_of"] + timedelta(days=2)),
    }]})
    assert scenario.status_code == 202, scenario.text
    _run_worker_until_idle(session_factory)
    scenario_path = f"/api/v1/forecasts/{scenario.json()['forecast_run_id']}"
    changed = client.get(scenario_path).json()
    assert changed["model_version"] == MODEL_VERSION
    assert changed["risk"]["probability_any_negative"] == 1
    comparison = client.get(scenario_path + "/comparison").json()
    assert comparison["risk"]["scenario"]["probability_status"] == "estimated_uncalibrated"
    assert client.get(path).json() == result
    assert client.get(f"/api/v1/forecasts/{old['forecast_run_id']}").json() == old_result
