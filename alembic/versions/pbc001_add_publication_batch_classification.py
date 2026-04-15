"""add publication batch classification table

Revision ID: pbc001_pub_batch_clf
Revises: tpl001_task_templates
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "pbc001_pub_batch_clf"
down_revision: Union[str, Sequence[str], None] = "tpl001_task_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publicacao_batches_classificacao",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("anthropic_batch_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="ENVIADO",
        ),
        sa.Column("anthropic_status", sa.String(), nullable=True),
        sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), server_default="0"),
        sa.Column("errored_count", sa.Integer(), server_default="0"),
        sa.Column("expired_count", sa.Integer(), server_default="0"),
        sa.Column("canceled_count", sa.Integer(), server_default="0"),
        sa.Column("record_ids", sa.JSON(), nullable=True),
        sa.Column("batch_metadata", sa.JSON(), nullable=True),
        sa.Column("model_used", sa.String(), nullable=True),
        sa.Column("requested_by_email", sa.String(), nullable=True),
        sa.Column("results_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_publicacao_batches_classificacao_anthropic_batch_id",
        "publicacao_batches_classificacao",
        ["anthropic_batch_id"],
    )
    op.create_index(
        "ix_publicacao_batches_classificacao_status",
        "publicacao_batches_classificacao",
        ["status"],
    )
    op.create_index(
        "ix_publicacao_batches_classificacao_requested_by_email",
        "publicacao_batches_classificacao",
        ["requested_by_email"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publicacao_batches_classificacao_requested_by_email",
        table_name="publicacao_batches_classificacao",
    )
    op.drop_index(
        "ix_publicacao_batches_classificacao_status",
        table_name="publicacao_batches_classificacao",
    )
    op.drop_index(
        "ix_publicacao_batches_classificacao_anthropic_batch_id",
        table_name="publicacao_batches_classificacao",
    )
    op.drop_table("publicacao_batches_classificacao")
