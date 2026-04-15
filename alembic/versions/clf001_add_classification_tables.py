"""add classification tables

Revision ID: clf001_classification
Revises: 1f3b7f2c9d4e
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "clf001_classification"
down_revision: Union[str, Sequence[str], None] = "1f3b7f2c9d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "classificacao_lotes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_filename", sa.String(), nullable=True),
        sa.Column("requested_by_email", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDENTE"),
        sa.Column("model_used", sa.String(), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), server_default="0"),
        sa.Column("failure_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_classificacao_lotes_status", "classificacao_lotes", ["status"])
    op.create_index("ix_classificacao_lotes_requested_by_email", "classificacao_lotes", ["requested_by_email"])

    op.create_table(
        "classificacao_itens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("classificacao_lotes.id"), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("process_number", sa.String(), nullable=False),
        sa.Column("publication_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDENTE"),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column("confidence", sa.String(), nullable=True),
        sa.Column("justification", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_classificacao_itens_batch_id", "classificacao_itens", ["batch_id"])
    op.create_index("ix_classificacao_itens_process_number", "classificacao_itens", ["process_number"])


def downgrade() -> None:
    op.drop_table("classificacao_itens")
    op.drop_table("classificacao_lotes")
