"""Атомарный импорт обязательств и сохранение происхождения документов."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261024_obligation_imports"
down_revision = "20261023_frozen_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "obligation_import",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("source_name", sa.String(40), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("items", JSONB(), nullable=False),
        sa.Column("errors", JSONB(), nullable=False),
        sa.Column("stats", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('previewed', 'committed')", name="status"),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "source_name", "content_sha256", "as_of",
                            name="uq_obligation_import_context"),
    )
    op.create_index("ix_obligation_import_company_id", "obligation_import", ["company_id"])
    for column in (
        sa.Column("counterparty_ref", sa.String(256), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("tax_regime", sa.Text(), nullable=True),
        sa.Column("source_payload", JSONB(), nullable=True),
    ):
        op.add_column("planned_event", column)


def downgrade() -> None:
    for name in ("source_payload", "tax_regime", "provenance", "counterparty_ref"):
        op.drop_column("planned_event", name)
    op.drop_index("ix_obligation_import_company_id", table_name="obligation_import")
    op.drop_table("obligation_import")
