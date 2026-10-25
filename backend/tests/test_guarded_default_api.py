"""Новый default проходит HTTP/очередь; старые задания и сценарии сохраняют1.0."""

import json
from datetime import date

from tests.test_integration import _run_worker_until_idle, _statement_csv, logged_in


def test_guarded_default_withholds_probability_and_keeps_preupgrade_job_and_scenario(
    client, session_factory, monkeypatch,
):
    from app.api.v1 import forecasts

    context = logged_in.__wrapped__(client, session_factory)
    company, account = context["company_id"], context["account_id"]
    preview = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account, "mapping": json.dumps({"date": "date", "amount": "amount",
                                                       "balance": "balance", "external_id": "op_id"}),
    }, files={"file": ("guarded.csv", _statement_csv(date(2026, 3, 1)), "text/csv")})
    assert preview.status_code == 200, preview.text
    assert client.post(f"/api/v1/imports/{preview.json()['import_id']}/commit").status_code == 200
    path = f"/api/v1/companies/{company}/forecasts"
    body = {"account_id": account, "as_of": "2026-03-01", "horizon_days": 30}
    real_factory = forecasts.get_forecast_service
    # Только тест имитирует enqueue до upgrade. Worker запускается уже при новом default.
    with monkeypatch.context() as old_app:
        old_app.setattr(forecasts, "get_forecast_service", lambda version=None:
                        real_factory(version if version is not None else "seasonal-block-bootstrap-1.0-w84"))
        previous = client.post(path, json=body)
        assert previous.status_code == 202, previous.text
    current = client.post(path, json=body)
    assert current.status_code == 202, current.text
    old_id, new_id = previous.json()["forecast_run_id"], current.json()["forecast_run_id"]
    assert old_id != new_id
    _run_worker_until_idle(session_factory)
    old_result = client.get(f"/api/v1/forecasts/{old_id}").json()
    new_result = client.get(f"/api/v1/forecasts/{new_id}").json()
    assert old_result["status"] == new_result["status"] == "succeeded"
    assert old_result["model_version"] == "seasonal-block-bootstrap-1.0-w84"
    assert new_result["model_version"] == "seasonal-damped-2.2-w84"
    assert new_result["risk"]["available"] is False
    assert new_result["risk"]["probability_any_negative"] is None
    assert all(point["probability_negative"] is None for point in new_result["points"])
    assert len(new_result["points"]) == 30
    assert client.get(f"/api/v1/forecasts/{new_id}/explanations").json()["available"] is True
    scenario = client.post(f"/api/v1/forecasts/{old_id}/scenarios", json={
        "changes": [{"kind": "add_expense", "amount_minor": 100000, "on_date": "2026-03-05"}],
    })
    assert scenario.status_code == 202, scenario.text
    _run_worker_until_idle(session_factory)
    old_scenario = client.get(f"/api/v1/forecasts/{scenario.json()['forecast_run_id']}").json()
    assert old_scenario["status"] == "succeeded"
    assert old_scenario["model_version"] == old_result["model_version"]
    assert old_scenario["points"][-1]["balance_p50_minor"] == old_result["points"][-1]["balance_p50_minor"] - 100000
    assert client.get(f"/api/v1/forecasts/{old_id}").json() == old_result
    assert client.post(path, json=body).json()["forecast_run_id"] == new_id
