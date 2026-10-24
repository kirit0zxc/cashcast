"""Сценарий принадлежит выбранной базе, даже если seed другой базы совпадает."""

import hashlib
import json

import pytest
from sqlalchemy import select

from app.core.models import ForecastRun
from tests.test_integration import _run_worker_until_idle, logged_in


@pytest.mark.parametrize("first_uses_legacy_hash", [False, True])
def test_same_change_and_output_seed_keep_distinct_base_lineage(
    client, session_factory, first_uses_legacy_hash,
):
    context = logged_in.__wrapped__(client, session_factory)
    request = {"account_id": context["account_id"], "as_of": "2026-03-01", "horizon_days": 30}
    bases = [client.post(f"/api/v1/companies/{context['company_id']}/forecasts",
                         json={**request, "seed": seed}).json()["forecast_run_id"]
             for seed in (42, 99)]
    _run_worker_until_idle(session_factory)
    originals = [client.get(f"/api/v1/forecasts/{base}").json() for base in bases]
    change = {"kind": "add_expense", "amount_minor": 10000, "on_date": "2026-03-05"}
    body = {"changes": [change], "seed": 99}
    first = client.post(f"/api/v1/forecasts/{bases[0]}/scenarios", json=body)
    assert first.status_code == 202, first.text
    if first_uses_legacy_hash:
        with session_factory.begin() as session:
            run = session.get(ForecastRun, first.json()["forecast_run_id"])
            run.scenario_hash = hashlib.sha256(json.dumps(
                run.scenario, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
    responses = [first, client.post(f"/api/v1/forecasts/{bases[1]}/scenarios", json=body)]
    assert [response.status_code for response in responses] == [202, 202]
    ids = [response.json()["forecast_run_id"] for response in responses]
    assert ids[0] != ids[1], "Сценарий другой базы ошибочно переиспользован по общему seed"
    _run_worker_until_idle(session_factory)
    for base, scenario in zip(bases, ids, strict=True):
        assert client.get(f"/api/v1/forecasts/{scenario}").json()["base_forecast_id"] == base
        repeated = client.post(f"/api/v1/forecasts/{base}/scenarios", json=body)
        assert repeated.status_code == 202 and repeated.json()["forecast_run_id"] == scenario
    # Смена seed первой базы остаётся явной причиной несовместимости, не скрывается.
    assert client.get(f"/api/v1/forecasts/{ids[0]}/comparison").status_code == 409
    comparison = client.get(f"/api/v1/forecasts/{ids[1]}/comparison")
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["base_forecast_id"] == bases[1]
    assert comparison.json()["points"][-1]["delta_balance_minor"] == -10000
    assert [client.get(f"/api/v1/forecasts/{base}").json() for base in bases] == originals
    with session_factory() as session:
        assert len(session.scalars(select(ForecastRun).where(
            ForecastRun.base_forecast_id.in_(bases),
        )).all()) == 2


def test_repeat_reuses_pre_upgrade_scenario_without_rewriting_it(client, session_factory):
    context = logged_in.__wrapped__(client, session_factory)
    base = client.post(f"/api/v1/companies/{context['company_id']}/forecasts", json={
        "account_id": context["account_id"], "as_of": "2026-03-01", "horizon_days": 30,
    }).json()["forecast_run_id"]
    _run_worker_until_idle(session_factory)
    body = {"changes": [{"kind": "add_expense", "amount_minor": 10000, "on_date": "2026-03-05"}]}
    accepted = client.post(f"/api/v1/forecasts/{base}/scenarios", json=body).json()
    _run_worker_until_idle(session_factory)
    with session_factory.begin() as session:
        run = session.get(ForecastRun, accepted["forecast_run_id"])
        # Имитируем сохранённый run прежней версии с её точным persisted payload.
        legacy_hash = hashlib.sha256(json.dumps(
            run.scenario, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        run.scenario_hash = legacy_hash
        frozen_input = run.input_snapshot
    original = client.get(f"/api/v1/forecasts/{accepted['forecast_run_id']}").json()
    repeated = client.post(f"/api/v1/forecasts/{base}/scenarios", json=body)
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["forecast_run_id"] == accepted["forecast_run_id"]
    assert repeated.json()["job_id"] == accepted["job_id"]
    with session_factory() as session:
        run = session.get(ForecastRun, accepted["forecast_run_id"])
        assert run.scenario_hash == legacy_hash and run.input_snapshot == frozen_input
    assert client.get(f"/api/v1/forecasts/{accepted['forecast_run_id']}").json() == original
