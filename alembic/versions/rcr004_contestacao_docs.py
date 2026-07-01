"""Análise Recursal: flag contestacao_com_documentos

Revision ID: rcr004_contestacao_docs
Revises: rcr003_data_intimacao
Create Date: 2026-07-01

Ponto crítico do Master: se a contestação foi juntada COM documentos
anexados (presença, não qualidade) — sinaliza ponto positivo na análise.
Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "rcr004_contestacao_docs"
down_revision = "rcr003_data_intimacao"
branch_labels = None
depends_on = None


def _has_col(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_col("analise_recursal", "contestacao_com_documentos"):
        op.add_column(
            "analise_recursal",
            sa.Column("contestacao_com_documentos", sa.Boolean(), nullable=True),
        )


def downgrade() -> None:
    if _has_col("analise_recursal", "contestacao_com_documentos"):
        op.drop_column("analise_recursal", "contestacao_com_documentos")
