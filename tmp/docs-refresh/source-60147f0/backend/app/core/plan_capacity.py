"""Совокупные лимиты планов под уже взятой блокировкой счёта (A016/B020)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.models import PlannedEvent
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR, ResourceLimits


class PlanCapacityPolicy:
    def __init__(self, session: Session):
        self.session = session

    def ensure_change(self, account_id: uuid.UUID, *, added_count: int, remaining_delta: int) -> None:
        if added_count <= 0 and remaining_delta <= 0:
            # Оплата/уменьшение должны помогать восстановлению даже старого переполненного счёта.
            return
        with self.session.no_autoflush:
            count, remaining = self.session.execute(select(
                func.count(PlannedEvent.id), func.coalesce(func.sum(PlannedEvent.remaining_amount_minor), 0),
            ).where(PlannedEvent.account_id == account_id)).one()
        if count + added_count > ResourceLimits().events or int(remaining) + remaining_delta > MAX_MONEY_MINOR:
            raise AppError(409, "forecast_capacity_exceeded",
                           "Набор планов превышает лимит прогноза: 2000 событий или общий денежный предел")
