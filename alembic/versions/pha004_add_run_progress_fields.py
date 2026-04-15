"""add progress fields to scheduled_automation_runs

Revision ID: pha004
Revises: pha003
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa


revision = "pha004"
down_revision = "pha003"
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
    table = "scheduled_automation_runs"
    if not _has_column(table, "progress_phase"):
        op.add_column(table, sa.Column("progress_phase", sa.String(), nullable=True))
    if not _has_column(table, "progress_current"):
        op.add_column(table, sa.Column("progress_current", sa.Integer(), nullable=True))
    if not _has_column(table, "progress_total"):
        op.add_column(table, sa.Column("progress_total", sa.Integer(), nullable=True))
    if not _has_column(table, "progress_message"):
        op.add_column(table, sa.Column("progress_message", sa.String(), nullable=True))
    if not _has_column(table, "progress_updated_at"):
        op.add_column(table, sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    table = "scheduled_automation_runs"
    for col in ("progress_updated_at", "progress_message", "progress_total", "progress_current", "progress_phase"):
        if _has_column(table, col):
            op.drop_column(table, col)
