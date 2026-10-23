"""Схемы запросов и ответов предметной области. Деньги в API — поле *_minor (целые копейки)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Direction = Literal["in", "out"]


# --- Auth ---
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class MeResponse(BaseModel):
    id: str
    email: str
    csrf_token: str = Field(description="Передавать в заголовке X-CSRF-Token на изменяющих запросах")
    companies: list[CompanyBrief]


class CompanyBrief(BaseModel):
    id: str
    name: str
    role: str


# --- Imports ---
class ColumnMappingIn(BaseModel):
    date: str
    amount: str | None = None
    inflow: str | None = None
    outflow: str | None = None
    direction: str | None = None
    counterparty_name: str | None = None
    counterparty_ref: str | None = None
    purpose: str | None = None
    external_id: str | None = None
    currency: str | None = None
    balance: str | None = None
    delimiter: str = ","
    encoding: str = "utf-8-sig"


class ImportPreviewResponse(BaseModel):
    import_id: str
    status: Literal["previewed", "committed", "failed"]
    total_rows: int
    error_count: int
    duplicate_in_file: int
    period_start: date | None
    period_end: date | None
    sample_errors: list[RowErrorOut]
    reused: bool = Field(description="True — такой файл уже загружали, вернули существующий импорт")


class RowErrorOut(BaseModel):
    row: int
    field: str
    message: str


class ImportCommitResponse(BaseModel):
    import_id: str
    status: str
    total_rows: int
    inserted: int
    skipped_existing: int
    duplicate_in_file: int
    error_count: int


# --- Transactions ---
class TransactionOut(BaseModel):
    id: str
    account_id: str
    booked_on: date
    amount_minor: int
    direction: Direction
    currency: str
    counterparty_name: str | None
    purpose: str | None
    category: str | None
    category_source: str | None
    category_confidence: float | None


class TransactionCategoryPatch(BaseModel):
    category: str = Field(min_length=1, max_length=50)


# --- Planned events ---
class PlannedEventIn(BaseModel):
    account_id: str | None = None
    direction: Direction
    amount_minor: int = Field(gt=0)
    due_date: date
    kind: Literal["invoice", "obligation", "tax", "manual"] = "manual"
    currency: str = "RUB"
    counterparty_name: str | None = None
    description: str | None = None
    category: str | None = None
    source_ref: str | None = None


class PlannedEventPatch(BaseModel):
    due_date: date | None = None
    amount_minor: int | None = Field(default=None, gt=0)
    status: Literal["planned", "partially_paid", "paid", "cancelled"] | None = None


class PlannedEventOut(BaseModel):
    id: str
    account_id: str | None
    direction: Direction
    amount_minor: int
    remaining_amount_minor: int
    currency: str
    due_date: date
    status: str
    kind: str
    source: str
    source_ref: str | None
    available_at: datetime
    counterparty_name: str | None
    category: str | None


# --- Forecasts & jobs ---
class ForecastRequest(BaseModel):
    account_id: str
    as_of: date
    horizon_days: int = Field(default=30, ge=1, le=180)
    seed: int | None = None


class JobAccepted(BaseModel):
    job_id: str
    forecast_run_id: str
    status: str


class JobStatusOut(BaseModel):
    id: str
    kind: str
    status: Literal["pending", "running", "succeeded", "failed"]
    forecast_run_id: str | None = None
    error_code: str | None = None


class ForecastPointOut(BaseModel):
    point_date: date
    inflow_minor: int
    outflow_minor: int
    balance_p10_minor: int
    balance_p50_minor: int
    balance_p90_minor: int
    probability_negative: float | None


class RiskOut(BaseModel):
    available: bool
    first_negative_date: date | None
    max_deficit_minor: int | None
    probability_any_negative: float | None


class ForecastOut(BaseModel):
    id: str
    account_id: str
    as_of: date
    horizon_days: int
    status: str
    model_version: str
    data_version: str
    seed: int
    opening_balance_minor: int | None
    base_forecast_id: str | None
    assumptions: list[str]
    data_warnings: list[str]
    risk: RiskOut
    points: list[ForecastPointOut]


class ExplanationItem(BaseModel):
    kind: str = Field(description="Тип причины: recurring_expense | planned_event | irregular_flow")
    label: str
    amount_minor: int | None = None
    source_ref: str | None = Field(default=None, description="Ссылка на конкретный источник причины")
    detail: dict = Field(default_factory=dict)


class ExplanationsOut(BaseModel):
    forecast_run_id: str
    available: bool
    summary: str
    items: list[ExplanationItem]


class ScenarioChangeIn(BaseModel):
    kind: Literal["delay_event", "reduce_irregular_inflow", "add_expense", "increase_recurring"]
    target_id: str | None = None
    shift_days: int | None = None
    factor: float | None = Field(default=None, gt=0, le=2)
    amount_minor: int | None = Field(default=None, gt=0)
    on_date: date | None = None


class ScenarioRequest(BaseModel):
    changes: list[ScenarioChangeIn] = Field(min_length=1)
    seed: int | None = None


MeResponse.model_rebuild()
ImportPreviewResponse.model_rebuild()
