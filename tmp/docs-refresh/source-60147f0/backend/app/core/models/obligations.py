"""Превью обязательств: нормализованные документы без хранения исходного CSV."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base, created_at_col, uuid_pk


class ObligationImport(Base):
    __tablename__ = "obligation_import"
    __table_args__ = (
        UniqueConstraint("account_id", "source_name", "content_sha256", "as_of",
                         name="uq_obligation_import_context"),
        CheckConstraint("status IN ('previewed', 'committed')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False,
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"),
    )
    source_name: Mapped[str] = mapped_column(String(40), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="previewed")
    # Исходные значения ошибок не сохраняем: только row/field/code и валидные документы.
    items: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    errors: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
