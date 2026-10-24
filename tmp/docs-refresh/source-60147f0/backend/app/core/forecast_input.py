"""Версионированный JSON-снимок чистых DTO: очередь не перечитывает изменившуюся БД."""

import json
from dataclasses import asdict
from datetime import date

from app.modules.contracts import (
    Category,
    DailyBalanceDTO,
    Direction,
    ForecastInput,
    PlannedEventDTO,
    RecurrenceGroup,
    RecurrenceInterval,
    ScenarioChange,
    TxnDTO,
)


class ForecastInputCodec:
    @staticmethod
    def encode(data: ForecastInput) -> dict:
        # date превращается в ISO; StrEnum уже JSON-совместим, деньги остаются int.
        return {"schema_version": 1, "input": json.loads(json.dumps(asdict(data), default=str))}

    @staticmethod
    def decode(snapshot: dict) -> ForecastInput:
        if snapshot.get("schema_version") != 1:
            raise ValueError("unsupported_snapshot_version")
        raw = snapshot["input"]
        return ForecastInput(
            account_id=raw["account_id"], as_of=date.fromisoformat(raw["as_of"]),
            horizon_days=raw["horizon_days"], opening_balance_minor=raw["opening_balance_minor"],
            seed=raw["seed"], data_version=raw["data_version"],
            txns=[TxnDTO(**{**t, "booked_on": date.fromisoformat(t["booked_on"]),
                            "direction": Direction(t["direction"])}) for t in raw["txns"]],
            daily_balances=[DailyBalanceDTO(**{**b, "balance_date": date.fromisoformat(b["balance_date"])})
                            for b in raw["daily_balances"]],
            planned_events=[PlannedEventDTO(**{**e, "due_date": date.fromisoformat(e["due_date"]),
                            "available_at": date.fromisoformat(e["available_at"]),
                            "direction": Direction(e["direction"])}) for e in raw["planned_events"]],
            recurrences=[RecurrenceGroup(**{**r, "direction": Direction(r["direction"]),
                         "interval": RecurrenceInterval(r["interval"]),
                         "category": Category(r["category"]) if r["category"] else None,
                         "next_expected_date": date.fromisoformat(r["next_expected_date"])
                         if r["next_expected_date"] else None}) for r in raw["recurrences"]],
            scenario=[ScenarioChange(**{**s, "on_date": date.fromisoformat(s["on_date"])
                      if s["on_date"] else None}) for s in raw["scenario"]],
        )
