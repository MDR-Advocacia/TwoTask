"""adiciona campos de tratado_por ao prazo_inicial_intakes

Replica o padrão de Publications (scheduled_by_*): registra QUEM
finalizou (Confirmar Agendamentos ou Finalizar Sem Providência) o
intake. Usado pela listagem do HITL pra mostrar "Tratado por: <nome>"
e habilitar filtro por operador.

Revision ID: pin011
Revises: pin010
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "pin011"
down_revision: Union[str, None] = "pin010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("treated_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("treated_by_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("treated_by_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("treated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index pra filtro por operador (e ordenação por data de tratamento).
    op.create_index(
        "ix_prazo_inicial_intakes_treated_by_user_id",
        "prazo_inicial_intakes",
        ["treated_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prazo_inicial_intakes_treated_by_user_id",
        table_name="prazo_inicial_intakes",
    )
    op.drop_column("prazo_inicial_intakes", "treated_at")
    op.drop_column("prazo_inicial_intakes", "treated_by_name")
    op.drop_column("prazo_inicial_intakes", "treated_by_email")
    op.drop_column("prazo_inicial_intakes", "treated_by_user_id")
