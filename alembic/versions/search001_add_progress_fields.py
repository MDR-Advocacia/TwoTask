"""Add progress tracking fields to publicacao_buscas.

Revision ID: search001_progress
Revises: tpl003_due_date_reference
Create Date: 2026-04-16

"""
from alembic import op
import sqlalchemy as sa

revision = "search001_progress"
down_revision = "tpl003_due_date_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publicacao_buscas", sa.Column("progress_step", sa.String(), nullable=True))
    op.add_column("publicacao_buscas", sa.Column("progress_detail", sa.String(), nullable=True))
    op.add_column("publicacao_buscas", sa.Column("progress_pct", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("publicacao_buscas", "progress_pct")
    op.drop_column("publicacao_buscas", "progress_detail")
    op.drop_column("publicacao_buscas", "progress_step")
