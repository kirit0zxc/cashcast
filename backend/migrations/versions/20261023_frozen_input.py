"""Сохранение входа прогноза при enqueue; прежние прогоны остаются читаемыми."""

from alembic import op
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261023_frozen_input"
down_revision = "887980e46a3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("forecast_run", Column("input_snapshot", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("forecast_run", "input_snapshot")
