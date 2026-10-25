"""Схемы запросов и ответов предметной области. Деньги в API — поле *_minor (целые копейки)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.core.limits import MAX_MONEY_MINOR
from app.modules.contracts import Category

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
    delimiter: str = Field(default=",", min_length=1, max_length=1)
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
    category: Category


# --- Planned events ---
class PlannedEventIn(BaseModel):
    account_id: UUID | None = None
    direction: Direction
    amount_minor: int = Field(gt=0, le=MAX_MONEY_MINOR, strict=True)
    due_date: date
    kind: Literal["invoice", "obligation", "tax", "manual"] = "manual"
    currency: str = "RUB"
    counterparty_name: str | None = Field(default=None, max_length=500)
    description: str | None = None
    category: str | None = Field(default=None, max_length=50)
    source_ref: str | None = Field(default=None, max_length=200)


class PlannedEventPatch(BaseModel):
    due_date: date | None = None
    amount_minor: int | None = Field(default=None, gt=0, le=MAX_MONEY_MINOR, strict=True)
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
    counterparty_ref: str | None = None
    provenance: str | None = None
    tax_regime: str | None = None
    category: str | None


# --- Forecasts & jobs ---
class ForecastRequest(BaseModel):
    account_id: UUID
    as_of: date = Field(ge=date(2, 1, 2))
    horizon_days: int = Field(default=30, ge=1, le=180)
    seed: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1, strict=True)


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


class MLFlagOut(BaseModel):
    available: bool
    flag: bool | None
    reason: str
    model_version: str
    horizon_days: Literal[30] = 30
    history_only: Literal[True] = True


class RiskOut(BaseModel):
    available: bool
    first_negative_date: date | None
    max_deficit_minor: int | None
    probability_any_negative: float | None
    probability_status: Literal["unavailable", "estimated_uncalibrated"] = "unavailable"
    probability_calibrated: Literal[False] = False
    ml_flag: MLFlagOut | None = None


class CalculationOut(BaseModel):
    mode: Literal["full", "incremental"]
    reason: str
    reused_history: bool
    bootstrap_paths_generated: int
    source_forecast_id: str | None = None
    categorized_transactions: int | None = None
    reused_transactions: int | None = None
    recurrence_buckets_recomputed: int | None = None
    daily_aggregates_changed: int | None = None
    trajectory_values_updated: int | None = None


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
    calculation: CalculationOut | None = None


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
    shift_days: int | None = Field(default=None, ge=0, le=3650, strict=True)
    factor: float | None = Field(default=None, ge=0, le=2)
    amount_minor: int | None = Field(default=None, gt=0, le=MAX_MONEY_MINOR, strict=True)
    on_date: date | None = None


class ScenarioRequest(BaseModel):
    changes: list[ScenarioChangeIn] = Field(min_length=1, max_length=50)
    seed: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1, strict=True)


MeResponse.model_rebuild()
ImportPreviewResponse.model_rebuild()
