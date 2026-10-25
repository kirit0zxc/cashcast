"""Дополнительный ML-флаг не меняет сохранённый прогноз и проверяется после доступа."""

import json
from datetime import date

import pytest

from app.core.config import get_settings
from app.core.forecast_input import ForecastInputCodec
from app.core.models import ForecastRun
from app.modules.forecasting.ml_flag import MLFlag
from tests.analytics.test_ml_flag import data
from tests.test_integration import _run_worker_until_idle, _statement_csv, logged_in


@pytest.fixture
def ml_context(client, session_factory):
    return logged_in.__wrapped__(client, session_factory)


def test_ml_flag_is_additive_and_requires_auth(client, session_factory, ml_context, monkeypatch):
    company, account = ml_context["company_id"], ml_context["account_id"]
    preview = client.post(f"/api/v1/companies/{company}/imports", data={
        "account_id": account,
        "mapping": json.dumps({"date": "date", "amount": "amount", "balance": "balance", "external_id": "op_id"}),
    }, files={"file": ("synthetic.csv", _statement_csv(date(2026, 3, 1)), "text/csv")}).json()
    assert client.post(f"/api/v1/imports/{preview['import_id']}/commit").status_code == 200
    job = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": "2026-03-01", "horizon_days": 30,
    }).json()
    _run_worker_until_idle(session_factory)
    url = f"/api/v1/forecasts/{job['forecast_run_id']}"
    baseline = client.get(url).json()
    assert baseline["status"] == "succeeded"
    # Для проверки границы API фиксируем искусственный полный snapshot, без сетевого ML.
    with session_factory() as session:
        run = session.get(ForecastRun, job["forecast_run_id"])
        run.input_snapshot = ForecastInputCodec.encode(data())
        session.commit()
    monkeypatch.setattr(get_settings(), "risk_ml_url", "http://risk-ml:8765")
    calls = []
    def predict(*args):
        calls.append(args)
        return True
    monkeypatch.setattr(MLFlag, "request", predict)
    updated = client.get(url).json()
    assert updated["risk"]["ml_flag"]["flag"] is True
    updated["risk"].pop("ml_flag")
    baseline["risk"].pop("ml_flag")
    assert updated == baseline
    assert len(calls) == 1
    # Даже существующий ID без сессии не должен вызывать сервис модели.
    assert client.post("/api/v1/auth/logout").status_code in (200, 204)
    assert client.get(url).status_code == 401
    assert len(calls) == 1
