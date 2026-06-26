"""Minha Equipe multi-time: equipe (setor) + is_supervisor em perf_pessoa

Revision ID: perf004_pessoa_equipe
Revises: perf003_relatorios
Create Date: 2026-06-26

Generaliza pra vários setores (supervisões). Cada pessoa do roster ganha:
- equipe        : slug do setor (ex.: 'bb-reu', 'master-reu'); agrupa abas da
                  planilha de squads (BB Réu = Defesa + Réu + Recursos).
- is_supervisor : marca a linha de supervisor(a) do setor.

Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "perf004_pessoa_equipe"
down_revision = "perf003_relatorios"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("perf_pessoa", "equipe"):
        op.add_column("perf_pessoa", sa.Column("equipe", sa.String(), nullable=True))
        op.create_index("ix_perf_pessoa_equipe", "perf_pessoa", ["equipe"])
    if not _has_column("perf_pessoa", "is_supervisor"):
        op.add_column(
            "perf_pessoa",
            sa.Column("is_supervisor", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    for c in ("is_supervisor", "equipe"):
        if _has_column("perf_pessoa", c):
            op.drop_column("perf_pessoa", c)
