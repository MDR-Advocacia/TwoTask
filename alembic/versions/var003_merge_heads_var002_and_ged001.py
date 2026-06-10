"""var003: merge heads var002 + ged001.

Revision ID: var003
Revises: var002, ged001
Create Date: 2026-06-07
"""

from alembic import op  # noqa: F401


revision = "var003"
down_revision = ("var002", "ged001")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
