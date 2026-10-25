"""Флаг отдельно от вероятности; сверка прошлого и безопасная недоступность."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, TxnDTO
from app.modules.forecasting.ml_flag import MODEL, MLFlag


def data():
    start = date(2026, 1, 1)
    days = [start + timedelta(days=i) for i in range(84)]
    return ForecastInput("a", days[-1], 30, 100000, 42,
        [TxnDTO(f"{i}-{direction}", "a", day, 1000, direction)
         for i, day in enumerate(days) for direction in (Direction.IN, Direction.OUT)],
        [DailyBalanceDTO("a", day, 100000) for day in days], [])


def test_payload_preserves_eod_flows_and_does_not_send_identity():
    payload = MLFlag.payload(ForecastInputCodec.encode(data()))
    assert len(payload["history"]) == 84 and payload["history"][-1]["balance"] == 100000
    assert payload["history"][0]["incoming"] == payload["history"][0]["outgoing"] == 1000
    assert set(payload) == {"as_of", "horizon_days", "history"}


@pytest.mark.parametrize("kind", ["short", "gaps", "negative", "horizon", "broken", "foreign"])
def test_invalid_or_unsupported_never_becomes_no_risk(kind):
    value = data()
    if kind == "short":
        value = replace(value, txns=value.txns[-10:], daily_balances=value.daily_balances[-5:])
    elif kind == "gaps":
        value = replace(value, txns=value.txns[:2], daily_balances=value.daily_balances[-1:])
    elif kind == "negative":
        value = replace(value, opening_balance_minor=-1)
    elif kind == "horizon":
        value = replace(value, horizon_days=7)
    elif kind == "broken":
        value = replace(value, daily_balances=[*value.daily_balances[:-1],
                                             replace(value.daily_balances[-1], closing_balance_minor=100001)])
    else:
        value = replace(value, txns=[replace(value.txns[0], account_id="other"), *value.txns[1:]])
    answer = MLFlag.assess(ForecastInputCodec.encode(value), "http://risk-ml:8765")
    assert answer["available"] is False and answer["flag"] is None


@pytest.mark.parametrize("flag", [True, False])
def test_binary_result_has_no_score_or_probability(monkeypatch, flag):
    monkeypatch.setattr(MLFlag, "request", lambda endpoint, payload: flag)
    answer = MLFlag.assess(ForecastInputCodec.encode(data()), "http://risk-ml:8765")
    assert answer["available"] and answer["flag"] is flag
    assert answer["model_version"] == MODEL
    assert "probability" not in answer and "score" not in answer


def test_model_failure_does_not_break_forecast(monkeypatch):
    def fail(*_args):
        raise TimeoutError
    monkeypatch.setattr(MLFlag, "request", fail)
    answer = MLFlag.assess(ForecastInputCodec.encode(data()), "http://risk-ml:8765")
    assert answer["flag"] is None and answer["reason"] == "model_unavailable"
    assert MLFlag.assess({}, None) is None
    assert MLFlag.assess(ForecastInputCodec.encode(data()), "http://risk-ml:8765",
                         scenario=True)["reason"] == "scenario_not_supported"
