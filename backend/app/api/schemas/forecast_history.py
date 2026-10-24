"""Метаданные сохранённых расчётов без входных выписок и payload очереди."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ForecastHistoryItem(BaseModel):
    id: UUID
    account_id: UUID
    as_of: date
    horizon_days: int
    status: Literal["pending", "running", "succeeded", "failed"]
    model_version: str
    data_version: str
    seed: int
    base_forecast_id: UUID | None
    created_at: datetime
    error_code: str | None
    job_id: UUID | None
