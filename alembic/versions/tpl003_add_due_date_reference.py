"""Add due_date_reference column to task_templates.

Revision ID: tpl003_due_date_reference
Revises: perf003_natureza_processo
Create Date: 2026-04-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "tpl003_due_date_reference"
down_revision = "perf003_natureza_processo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_templates",
        sa.Column(
            "due_date_reference",
            sa.String(),
            nullable=False,
            server_default="publication",
        ),
    )


def downgrade() -> None:
    op.drop_column("task_templates", "due_date_reference")
