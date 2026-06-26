"""Minha Equipe: team em perf_relatorio (relatório de setor por time)

Revision ID: perf005_relatorio_team
Revises: perf004_pessoa_equipe
Create Date: 2026-06-26

O relatório PDF do setor agora é por time — guarda o slug do time no job.
Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "perf005_relatorio_team"
down_revision = "perf004_pessoa_equipe"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("perf_relatorio", "team"):
        op.add_column("perf_relatorio", sa.Column("team", sa.String(), nullable=True))


def downgrade() -> None:
    if _has_column("perf_relatorio", "team"):
        op.drop_column("perf_relatorio", "team")
