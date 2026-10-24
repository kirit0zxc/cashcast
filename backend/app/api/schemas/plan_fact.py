"""HTTP plan-fact-api-v1: подтверждённые суммы отдельно от альтернативных предложений."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.models import PlannedEventOut
from app.core.limits import MAX_MONEY_MINOR


class PlanFactConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    planned_event_id: UUID
    transaction_id: UUID
    matched_amount_minor: int = Field(strict=True, gt=0, le=MAX_MONEY_MINOR)


class PlanFactItem(BaseModel):
    event: PlannedEventOut
    confirmed_amount_minor: int


class ConfirmedMatchOut(BaseModel):
    planned_event_id: str
    transaction_id: str
    matched_amount_minor: int


class MatchProposalOut(ConfirmedMatchOut):
    confidence: float
    reason: str
    auto_confirm: bool


class PlanFactOut(BaseModel):
    account_id: str
    as_of: date
    items: list[PlanFactItem]
    confirmed_matches: list[ConfirmedMatchOut]
    proposals: list[MatchProposalOut]
