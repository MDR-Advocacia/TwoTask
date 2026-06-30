"""Balanceador: destinos recorrentes da distribuição em fila

Revision ID: bal002_fila_pref
Revises: bal001_balanceador_log
Create Date: 2026-06-29

Aprende os destinos recorrentes por (origem, subtipo) pra sugerir no topo nas
próximas distribuições em fila. Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "bal002_fila_pref"
down_revision = "bal001_balanceador_log"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("balanceador_fila_pref"):
        return
    op.create_table(
        "balanceador_fila_pref",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team", sa.String(), nullable=True, index=True),
        sa.Column("origem_pessoa_id", sa.Integer(), nullable=False, index=True),
        sa.Column("subtipo", sa.String(), nullable=False),
        sa.Column("alvo_id", sa.Integer(), nullable=True),
        sa.Column("alvo_nome", sa.String(), nullable=False),
        sa.Column("vezes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ultimo_uso", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("origem_pessoa_id", "subtipo", "alvo_nome", name="uq_fila_pref"),
    )


def downgrade() -> None:
    if _has_table("balanceador_fila_pref"):
        op.drop_table("balanceador_fila_pref")
