"""Сохранение правил B в операциях; ручные исправления пользователя не перезаписываются."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.models import BankTransaction
from app.modules.categorization.service import get_categorizer
from app.modules.contracts import Direction, TxnDTO


class TransactionCategorization:
    def __init__(self, session: Session):
        self.session = session

    def refresh(self, account_id) -> None:
        rows = self.session.scalars(select(BankTransaction).where(
            BankTransaction.account_id == account_id,
            or_(BankTransaction.category_source.is_(None), BankTransaction.category_source != "manual"),
        ).order_by(BankTransaction.id).with_for_update()).all()
        by_id = {str(t.id): t for t in rows}
        inputs = [TxnDTO(
            id=str(t.id), account_id=str(t.account_id), booked_on=t.booked_on,
            amount_minor=t.amount_minor, direction=Direction(t.direction), currency=t.currency,
            counterparty_name=t.counterparty_name, counterparty_ref=t.counterparty_ref, purpose=t.purpose,
        ) for t in rows]
        for assignment in get_categorizer().categorize(inputs):
            row = by_id[assignment.transaction_id]
            row.category = assignment.category.value
            row.category_source = "auto"
            row.category_confidence = assignment.confidence
            row.category_reason = assignment.reason
        self.session.flush()
