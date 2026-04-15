"""add task templates table

Revision ID: tpl001_task_templates
Revises: pub001_publication_search
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "tpl001_task_templates"
down_revision: Union[str, Sequence[str], None] = "pub001_publication_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column(
            "office_external_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_offices.external_id"),
            nullable=False,
        ),
        sa.Column(
            "task_subtype_external_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_task_subtypes.external_id"),
            nullable=False,
        ),
        sa.Column(
            "responsible_user_external_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.external_id"),
            nullable=False,
        ),
        sa.Column("priority", sa.String(), nullable=False, server_default="Normal"),
        sa.Column("due_business_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("description_template", sa.Text(), nullable=True),
        sa.Column("notes_template", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "category",
            "subcategory",
            "office_external_id",
            name="uq_task_template_classification_office",
        ),
    )
    op.create_index("ix_task_templates_category", "task_templates", ["category"])
    op.create_index("ix_task_templates_subcategory", "task_templates", ["subcategory"])
    op.create_index("ix_task_templates_office_external_id", "task_templates", ["office_external_id"])
    op.create_index("ix_task_templates_task_subtype_external_id", "task_templates", ["task_subtype_external_id"])
    op.create_index("ix_task_templates_responsible_user_external_id", "task_templates", ["responsible_user_external_id"])
    op.create_index("ix_task_templates_is_active", "task_templates", ["is_active"])


def downgrade() -> None:
    op.drop_table("task_templates")
