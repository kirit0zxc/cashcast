"""Отдельный бинарный ML-сигнал: не изменяет вероятность и траектории прогноза."""

import http.client
import json
from collections import defaultdict
from datetime import timedelta
from functools import lru_cache
from urllib.parse import urlsplit

from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import Direction
from app.modules.forecasting.v2.quality import assess_quality, validate_input

MODEL = "cashcast-risk-sr04-frozen-20261025"


class MLFlag:
    @staticmethod
    def unavailable(reason):
        return {"available": False, "flag": None, "reason": reason, "model_version": MODEL,
                "horizon_days": 30, "history_only": True}

    @staticmethod
    def payload(snapshot):
        data = validate_input(ForecastInputCodec.decode(snapshot))
        if data.scenario:
            raise ValueError("scenario_not_supported")
        if data.horizon_days != 30:
            raise ValueError("requires_30_days")
        if data.opening_balance_minor < 0:
            raise ValueError("already_negative")
        quality = assess_quality(data, 84)
        if (quality.history_days < 84 or not quality.eligible_for_probability
                or quality.unobserved_calendar_days > 0):
            raise ValueError("insufficient_verified_history")
        flows = defaultdict(lambda: [0, 0])
        for txn in data.txns:
            flows[txn.booked_on][0 if txn.direction == Direction.IN else 1] += txn.amount_minor
        anchors = {b.balance_date: b.closing_balance_minor for b in data.daily_balances}
        balance, rows = data.opening_balance_minor, []
        for offset in range(84):
            day = data.as_of - timedelta(days=offset)
            if day in anchors and anchors[day] != balance:
                raise ValueError("unreconciled_balances")
            incoming, outgoing = flows[day]
            rows.append({"date": day.isoformat(), "incoming": incoming, "outgoing": outgoing, "balance": balance})
            balance -= incoming - outgoing
        return {"as_of": data.as_of.isoformat(), "horizon_days": 30, "history": list(reversed(rows))}

    @staticmethod
    @lru_cache(maxsize=128)
    def request(endpoint, payload):
        url = urlsplit(endpoint)
        if url.scheme != "http" or not url.hostname or url.path not in {"", "/"}:
            raise ValueError("invalid_service_url")
        connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=3)
        try:
            connection.request("POST", "/predict", body=payload.encode(), headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(16385)
            if response.status != 200 or len(raw) > 16384:
                raise ValueError("model_unavailable")
            result = json.loads(raw)
            if result.get("model_version") != MODEL or type(result.get("alert")) is not bool:
                raise ValueError("invalid_model_response")
            # Ни score, ни probability из модели не возвращаются клиенту как вероятность.
            return result["alert"]
        finally:
            connection.close()

    @classmethod
    def assess(cls, snapshot, endpoint, *, scenario=False, ready=True):
        if not endpoint:
            return None
        if not ready or not snapshot:
            return cls.unavailable("forecast_not_ready")
        if scenario:
            return cls.unavailable("scenario_not_supported")
        try:
            payload = cls.payload(snapshot)
        except (ValueError, KeyError, TypeError):
            return cls.unavailable("insufficient_verified_history_or_unsupported_input")
        try:
            flag = cls.request(endpoint, json.dumps(payload, sort_keys=True, separators=(",", ":")))
        except (OSError, ValueError, http.client.HTTPException):
            return cls.unavailable("model_unavailable")
        return {"available": True, "flag": flag, "reason": "history_only", "model_version": MODEL,
                "horizon_days": 30, "history_only": True}
