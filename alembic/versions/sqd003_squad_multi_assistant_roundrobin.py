"""squad_members.last_assigned_at — base do round-robin entre assistentes

Permite multiplos assistentes por squad. Quando uma tarefa entra como
'assistente', o resolver pega o membro com `is_assistant=True` que ficou
mais tempo sem receber (ORDER BY last_assigned_at NULLS FIRST, id) e
atualiza `last_assigned_at = now()` em transacao com a criacao da tarefa.

Decisao tomada com user em 2026-05-04: distribuicao igual entre
assistentes via fila interna; operador na ponta da operacao tem ultima
palavra (override manual desliga a regra).

Revision ID: sqd003
Revises: sqd002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "sqd003"
down_revision: Union[str, None] = "sqd002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "squad_members",
        sa.Column(
            "last_assigned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_squad_members_last_assigned_at",
        "squad_members",
        ["last_assigned_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_squad_members_last_assigned_at", table_name="squad_members")
    op.drop_column("squad_members", "last_assigned_at")
