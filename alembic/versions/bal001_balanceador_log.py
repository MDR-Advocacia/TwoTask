"""Balanceador de Agenda: tabela de log de redistribuição

Revision ID: bal001_balanceador_log
Revises: perf005_relatorio_team
Create Date: 2026-06-29

Log de cada redistribuição executada (o que foi movido, de quem pra quem, quais
tarefas) — listado na aba Relatórios do Minha Equipe. Idempotente.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "bal001_balanceador_log"
down_revision = "perf005_relatorio_team"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("balanceador_log"):
        return
    op.create_table(
        "balanceador_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team", sa.String(), nullable=True, index=True),
        sa.Column("criado_por_id", sa.Integer(), nullable=True),
        sa.Column("criado_por_nome", sa.String(), nullable=True),
        sa.Column("total_movimentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tarefas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origem", sa.String(), nullable=False, server_default="mock"),
        sa.Column("detalhe", JSONB(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # índice de `team` já é criado pelo index=True da coluna no create_table.


def downgrade() -> None:
    if _has_table("balanceador_log"):
        op.drop_table("balanceador_log")
