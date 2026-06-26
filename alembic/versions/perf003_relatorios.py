"""Minha Equipe: relatórios PDF como trabalho persistente (perf_relatorio)

Revision ID: perf003_relatorios
Revises: perf002_minha_equipe_perm
Create Date: 2026-06-26

Em vez de gerar o PDF preso ao navegador (que se perde se a pessoa sai), o
relatório vira um JOB no servidor: dispara → gera em background → guarda o PDF
na linha → fica disponível pra baixar a qualquer momento.

perf_relatorio:
- tipo          : 'setor' | 'pessoa';
- status        : 'processando' | 'pronto' | 'erro';
- pdf           : bytes do PDF (preenchido quando pronto);
- criado_por_id : dono do relatório (cada um vê os seus).

Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "perf003_relatorios"
down_revision = "perf002_minha_equipe_perm"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("perf_relatorio"):
        op.create_table(
            "perf_relatorio",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tipo", sa.String(), nullable=False),
            sa.Column("pessoa_id", sa.Integer(), nullable=True),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("status", sa.String(), nullable=False, server_default="processando"),
            sa.Column("pdf", sa.LargeBinary(), nullable=True),
            sa.Column("erro", sa.String(), nullable=True),
            sa.Column("criado_por_id", sa.Integer(), nullable=True),
            sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("concluido_em", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_perf_relatorio_dono", "perf_relatorio", ["criado_por_id", "criado_em"])


def downgrade() -> None:
    if _has_table("perf_relatorio"):
        op.drop_table("perf_relatorio")
