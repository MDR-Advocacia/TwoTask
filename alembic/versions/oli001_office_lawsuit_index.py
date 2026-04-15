"""Office lawsuit index (cache persistente de processos por escritório)

Revision ID: oli001_office_lawsuit_index
Revises: tpl002_drop_uq_clf_office
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "oli001_office_lawsuit_index"
down_revision: Union[str, Sequence[str], None] = "tpl002_drop_uq_clf_office"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "office_lawsuit_index",
        sa.Column("office_id", sa.Integer(), nullable=False),
        sa.Column("lawsuit_id", sa.Integer(), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("office_id", "lawsuit_id"),
    )
    op.create_index(
        "ix_office_lawsuit_index_office",
        "office_lawsuit_index",
        ["office_id"],
    )
    op.create_index(
        "ix_office_lawsuit_index_lawsuit",
        "office_lawsuit_index",
        ["lawsuit_id"],
    )

    op.create_table(
        "office_lawsuit_sync",
        sa.Column("office_id", sa.Integer(), primary_key=True),
        sa.Column("last_full_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_incremental_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=32), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("total_ids", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_progress", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supports_incremental", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table("office_lawsuit_sync")
    op.drop_index("ix_office_lawsuit_index_lawsuit", table_name="office_lawsuit_index")
    op.drop_index("ix_office_lawsuit_index_office", table_name="office_lawsuit_index")
    op.drop_table("office_lawsuit_index")
