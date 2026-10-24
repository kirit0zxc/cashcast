"""План-факт доступной компании: GET только читает, POST применяет безопасные совпадения."""

import uuid
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.plan_fact import (
    ConfirmedMatchOut,
    MatchProposalOut,
    PlanFactConfirmRequest,
    PlanFactItem,
    PlanFactOut,
)
from app.api.v1.planned_events import _to_out
from app.core.auth import require_company_access
from app.core.deps import get_db
from app.modules.integration.manual_confirmation import ManualPlanFactConfirmation
from app.modules.integration.plan_fact import PlanFactService

router = APIRouter(tags=["plan-fact"], responses=ERROR_RESPONSES)


def _response(account_id: uuid.UUID, as_of: date, data: dict) -> PlanFactOut:
    return PlanFactOut(
        account_id=str(account_id), as_of=as_of,
        items=[PlanFactItem(event=_to_out(e), confirmed_amount_minor=data["confirmed"].get(str(e.id), 0))
               for e in data["events"]],
        confirmed_matches=[ConfirmedMatchOut(
            planned_event_id=str(link.planned_event_id), transaction_id=str(link.transaction_id),
            matched_amount_minor=link.matched_amount_minor,
        ) for link in data["links"]],
        proposals=[MatchProposalOut(**asdict(p)) for p in data["proposals"]],
    )


@router.get("/companies/{company_id}/plan-fact", response_model=PlanFactOut)
def plan_fact(company_id: uuid.UUID, account_id: uuid.UUID, as_of: date,
              _company: str = Depends(require_company_access),
              session: Session = Depends(get_db, scope="function")) -> PlanFactOut:
    return _response(account_id, as_of, PlanFactService(session).run(company_id, account_id, as_of))


@router.post("/companies/{company_id}/plan-fact", response_model=PlanFactOut)
def reconcile(company_id: uuid.UUID, account_id: uuid.UUID, as_of: date,
              _company: str = Depends(require_company_access),
              session: Session = Depends(get_db, scope="function")) -> PlanFactOut:
    return _response(account_id, as_of, PlanFactService(session).run(company_id, account_id, as_of, write=True))


@router.post("/companies/{company_id}/plan-fact/confirm", response_model=PlanFactOut)
def confirm_proposal(company_id: uuid.UUID, body: PlanFactConfirmRequest,
                     _company: str = Depends(require_company_access),
                     session: Session = Depends(get_db, scope="function")) -> PlanFactOut:
    data = ManualPlanFactConfirmation(session).confirm(
        company_id, body.account_id, body.planned_event_id, body.transaction_id, body.matched_amount_minor,
    )
    return _response(body.account_id, data["as_of"], data)
