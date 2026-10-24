"""Подтверждения действий и учёт обращений к ассистенту."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261024_assistant"
down_revision = "20261024_obligation_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("assistant_turn", "assistant_action"):
        columns = [
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("company.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        ]
        if name == "assistant_turn":
            columns += [sa.Column("request_id", UUID(as_uuid=True), nullable=False),
                        sa.Column("input_hash", sa.String(64), nullable=False),
                        sa.Column("response", JSONB, nullable=False), sa.UniqueConstraint("user_id", "request_id")]
        else:
            columns += [sa.Column("name", sa.String(50), nullable=False),
                        sa.Column("arguments", JSONB, nullable=False),
                        sa.Column("fingerprint", sa.String(64), nullable=False),
                        sa.Column("status", sa.String(20), nullable=False),
                        sa.Column("result", JSONB, nullable=False),
                        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False)]
        op.create_table(name, *columns)
        op.create_index(f"ix_{name}_user_id", name, ["user_id"])


def downgrade() -> None:
    op.drop_table("assistant_action")
    op.drop_table("assistant_turn")
