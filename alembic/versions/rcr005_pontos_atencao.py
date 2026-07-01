"""Análise Recursal: pontos_de_atencao (checklist interno de revisão)

Revision ID: rcr005_pontos_atencao
Revises: rcr004_contestacao_docs
Create Date: 2026-07-01

Quando o diagnóstico não é seguro, o motor lista dicas incisivas pro
advogado do que olhar/avaliar no caso concreto (guia interno, não vai no
parecer do cliente). Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "rcr005_pontos_atencao"
down_revision = "rcr004_contestacao_docs"
branch_labels = None
depends_on = None


def _has_col(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_col("analise_recursal", "pontos_de_atencao"):
        op.add_column(
            "analise_recursal",
            sa.Column("pontos_de_atencao", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _has_col("analise_recursal", "pontos_de_atencao"):
        op.drop_column("analise_recursal", "pontos_de_atencao")
