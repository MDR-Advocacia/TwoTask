"""Minha Equipe: permissão de acesso + equipes permitidas por usuário

Revision ID: perf002_minha_equipe_perm
Revises: perf001_minha_equipe
Create Date: 2026-06-26

Árvore de permissões do "Minha Equipe" no admin:
- can_use_minha_equipe : libera o menu MINHA EQUIPE pro usuário (admin ignora).
- minha_equipe_equipes : CSV das chaves de equipe que o usuário pode ver
                         (ex.: "bb-reu"); vazio/NULL = nenhuma.

Idempotente (guard por has_column).
"""

from alembic import op
import sqlalchemy as sa


revision = "perf002_minha_equipe_perm"
down_revision = "perf001_minha_equipe"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("legal_one_users", "can_use_minha_equipe"):
        op.add_column(
            "legal_one_users",
            sa.Column("can_use_minha_equipe", sa.Boolean(), nullable=False, server_default="false"),
        )
    if not _has_column("legal_one_users", "minha_equipe_equipes"):
        op.add_column(
            "legal_one_users",
            sa.Column("minha_equipe_equipes", sa.String(), nullable=True),
        )


def downgrade() -> None:
    for c in ("minha_equipe_equipes", "can_use_minha_equipe"):
        if _has_column("legal_one_users", c):
            op.drop_column("legal_one_users", c)
