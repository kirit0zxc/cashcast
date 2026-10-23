"""HTTP plan-fact-api-v1: подтверждённые суммы отдельно от альтернативных предложений."""

from datetime import date

from pydantic import BaseModel

from app.api.schemas.models import PlannedEventOut


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
