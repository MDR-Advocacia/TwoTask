"""add initial_lookback_days and overlap_hours to scheduled_automations

Revision ID: pha003
Revises: pha002
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa


revision = "pha003"
down_revision = "pha002"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    res = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return bool(res)


def upgrade() -> None:
    table = "scheduled_automations"
    if not _has_column(table, "initial_lookback_days"):
        op.add_column(table, sa.Column("initial_lookback_days", sa.Integer(), nullable=True))
    if not _has_column(table, "overlap_hours"):
        op.add_column(table, sa.Column("overlap_hours", sa.Integer(), nullable=True))


def downgrade() -> None:
    table = "scheduled_automations"
    for col in ("overlap_hours", "initial_lookback_days"):
        if _has_column(table, col):
            op.drop_column(table, col)
