"""Add classification_feedbacks table.

Revision ID: fb001_classification_feedback
Revises: search001_progress
Create Date: 2026-04-16

"""
from alembic import op
import sqlalchemy as sa

revision = "fb001_classification_feedback"
down_revision = "search001_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classification_feedbacks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("publicacao_registros.id"), nullable=False, index=True),
        sa.Column("feedback_type", sa.String(), nullable=False, index=True),
        sa.Column("original_category", sa.String(), nullable=True),
        sa.Column("original_subcategory", sa.String(), nullable=True),
        sa.Column("original_polo", sa.String(), nullable=True),
        sa.Column("original_natureza", sa.String(), nullable=True),
        sa.Column("corrected_category", sa.String(), nullable=False),
        sa.Column("corrected_subcategory", sa.String(), nullable=True),
        sa.Column("corrected_polo", sa.String(), nullable=True),
        sa.Column("corrected_natureza", sa.String(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("user_note", sa.Text(), nullable=True),
        sa.Column("text_excerpt", sa.Text(), nullable=True),
        sa.Column("office_external_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_by_email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("classification_feedbacks")
