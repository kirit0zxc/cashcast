"""Ранний SQL-контроль числа строк до ORM и аналитики, с теми же лимитами модели."""

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.models import BankTransaction, DailyBalance, PlannedEvent
from app.modules.forecasting.v2.quality import ResourceLimits


class SnapshotRowBudget:
    def __init__(self, session: Session):
        self.session = session
        self.limits = ResourceLimits()

    def ensure_account(self, account_id: uuid.UUID | str, as_of: date, *, include_balances: bool = True) -> None:
        cutoff = datetime.combine(as_of, time.max, UTC)
        for model, available, maximum in (
            (BankTransaction, BankTransaction.booked_on <= as_of, self.limits.transactions),
            (DailyBalance, DailyBalance.balance_date <= as_of, self.limits.balances),
            (PlannedEvent, PlannedEvent.available_at <= cutoff, self.limits.events),
        ):
            if model is DailyBalance and not include_balances:
                # Самому план-факту остатки не нужны; полный прогноз проверяет их отдельно.
                continue
            # COUNT всего счёта не нужен: подзапрос возвращает максимум limit+1 идентификаторов.
            bounded = select(model.id).where(model.account_id == account_id, available).limit(maximum + 1).subquery()
            count = self.session.scalar(select(func.count()).select_from(bounded))
            self.ensure_count(count, maximum)

    @staticmethod
    def ensure_count(count: int, maximum: int) -> None:
        if count > maximum:
            raise AppError(422, "forecast_resource_limit", "Вход превышает лимит операций, остатков или планов")
