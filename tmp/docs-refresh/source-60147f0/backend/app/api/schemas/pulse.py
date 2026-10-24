"""Полный контракт пульса, включая состояния без операций и без рекомендаций."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

Status = Literal["ok", "watch", "risk", "unknown"]


class PulseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PulseAction(PulseModel):
    urgency: Literal["now", "this_month", "later"]
    title: str
    why: str
    amount_minor: int
    source: Literal["cash", "money", "clients"]


class PulseStep(PulseModel):
    title: str
    amount_minor: int
    cost_minor: int
    details: list[str]


class PulseSuggestion(PulseModel):
    title: str
    details: list[str]


class PulsePlan(PulseModel):
    title: str
    resolved: bool
    steps: list[PulseStep]
    credit_minor: int
    credit_cost_minor: int
    holds_if_inflows_drop_20pct: bool


class PulseChart(PulseModel):
    days: list[date]
    base_minor: list[int]
    if_owner_withdraws_minor: list[int] | None
    after_plan_minor: list[int] | None
    buffer_minor: int


class PulseCash(PulseModel):
    status: Status
    message: str
    first_gap_date: date | None
    days_until_gap: int | None
    max_deficit_minor: int
    gap_only_if_owner_withdraws: bool
    structural_shortfall: bool
    buffer_minor: int
    buffer_source: Literal["user", "auto"]
    plan: PulsePlan | None
    suggestions: list[PulseSuggestion]
    chart: PulseChart
    warnings: list[str]
    assumptions: list[str]


class PulseFinding(PulseModel):
    kind: str
    nature: Literal["loss", "opportunity", "signal", "frozen"]
    certainty: Literal["fact", "estimate"]
    title: str
    amount_minor: int
    period: Literal["year", "window"]
    evidence: list[str]
    action: str
    blocked_by_cash_gap: bool


class PulseMoney(PulseModel):
    status: Status
    loss_per_year_minor: int
    opportunity_per_year_minor: int
    opportunity_deferred_minor: int
    one_off_loss_minor: int
    frozen_minor: int
    signals: int
    findings: list[PulseFinding]
    assumptions: list[str]
    warnings: list[str]


class PulseClient(PulseModel):
    name: str | None
    share: float
    grade: str
    grade_label: str


class PulseClientRisk(PulseClient):
    reasons: list[str]


class PulseStress(PulseModel):
    title: str
    text: str
    kind: Literal["delay", "loss"]
    first_gap_date: date | None
    creates_gap: bool
    worst_day_shortfall_minor: int
    basis: str


class PulseClients(PulseModel):
    applicable: bool
    status: Status
    message: str
    top_client: PulseClient | None
    at_risk: list[PulseClientRisk]
    stress: list[PulseStress]


class PulseOut(PulseModel):
    forecast_id: str
    account_id: str
    company_id: str
    as_of: date
    model_version: str
    data_version: str
    method_version: str
    status: Status
    headline: str
    cash: PulseCash
    money: PulseMoney
    clients: PulseClients
    actions: list[PulseAction]
    warnings: list[str]
