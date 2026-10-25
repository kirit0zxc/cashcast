"""Карточка дефицита и несохраняемый расчёт действий над frozen-медианой."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR

Money = Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_MINOR)]


class GapModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GapEpisode(GapModel):
    kind: Literal["existing", "new"]
    first_negative_date: date
    last_negative_date: date
    recovery_date: date | None
    observed_days: int
    duration_is_lower_bound: bool
    max_deficit_minor: int
    worst_date: date


class GapSummary(GapModel):
    status: Literal["gap", "no_gap", "insufficient_data"]
    opening_already_negative: bool
    first_new_gap_date: date | None
    days_until_new_gap: int | None = None
    # Резерв на начало ряда без будущего возврата; не размер одобренного кредита.
    required_reserve_minor: int = 0
    max_deficit_minor: int
    total_negative_days: int
    episodes: list[GapEpisode]


class GapFlow(GapModel):
    id: str
    source_ref: str | None
    date: date
    amount_minor: int
    label: str
    evidence: Literal["planned", "estimated", "scenario"]
    delay_allowed: bool


class GapCause(GapModel):
    date: date
    amount_minor: int
    label: str
    evidence: Literal["observed", "planned", "estimated", "scenario"]
    source_ref: str | None = None


class GapPoint(GapModel):
    date: date
    base_minor: int
    preview_minor: int
    delta_minor: int


class CashGapOut(GapModel):
    forecast_id: str
    method_version: Literal["cash-gaps-1.0"] = "cash-gaps-1.0"
    as_of: date
    horizon_end: date
    model_version: str
    data_version: str
    base: GapSummary
    preview: GapSummary
    points: list[GapPoint]
    flows: list[GapFlow]
    causes: list[GapCause]
    causes_date: date
    causes_balance_minor: int
    probability: float | None = Field(default=None, ge=0, le=1)
    probability_status: Literal["unavailable", "estimated_uncalibrated"] = "unavailable"
    probability_reason: str
    quality_mode: str
    improvement_minor: int
    financing_cost_minor: int
    debt_beyond_horizon_minor: int
    warnings: list[str]


class GapDelay(GapModel):
    kind: Literal["delay"]
    flow_id: str = Field(min_length=1, max_length=100)
    to_date: date
    # Это согласие на гипотезу допустимости, а не команда изменить реальный платёж.
    payment_delay_agreed: bool = False


class GapFunding(GapModel):
    kind: Literal["financing"]
    date: date
    amount_minor: Annotated[int, Field(strict=True, gt=0, le=MAX_MONEY_MINOR)]
    repayment_date: date
    cost_minor: Money


class CashGapPreview(GapModel):
    actions: list[Annotated[GapDelay | GapFunding, Field(discriminator="kind")]] = Field(min_length=1, max_length=3)
