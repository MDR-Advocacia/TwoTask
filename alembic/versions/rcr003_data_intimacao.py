"""Análise Recursal: coluna data_intimacao (base do prazo fatal computado)

Revision ID: rcr003_data_intimacao
Revises: rcr002_seed_custas
Create Date: 2026-07-01

A IA extrai a data de intimação/publicação da decisão; o código calcula o
prazo fatal = +N dias úteis (15 apelação/agravo, 5 embargos) de forma
determinística. Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "rcr003_data_intimacao"
down_revision = "rcr002_seed_custas"
branch_labels = None
depends_on = None


def _has_col(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_col("analise_recursal", "data_intimacao"):
        op.add_column(
            "analise_recursal",
            sa.Column("data_intimacao", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    if _has_col("analise_recursal", "data_intimacao"):
        op.drop_column("analise_recursal", "data_intimacao")
