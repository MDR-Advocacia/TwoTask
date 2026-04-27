"""adiciona dispatch_pending ao prazo_inicial_intakes

Onda 3 #5 — desacopla disparo automático de GED + cancel da legacy task
do passo de Confirmar/Finalizar. Após o operador confirmar (ou finalizar
sem providência) no HITL, o intake fica AGENDADO/CONCLUIDO_SEM_PROVIDENCIA
mas com `dispatch_pending=True`. O disparo (GED upload + enqueue cancel)
acontece via:
- Botão manual "Disparar agora" na Tratamento Web
- Worker periódico (Onda 3 #6) com batch limit configurável

Revision ID: pin012
Revises: pin011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "pin012"
down_revision: Union[str, None] = "pin011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "dispatch_pending",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("dispatch_error_message", sa.Text(), nullable=True),
    )
    # Index principal usado pelo worker periódico (varre intakes
    # pendentes em ordem cronológica) e pelo filtro do listing.
    op.create_index(
        "ix_prazo_inicial_intakes_dispatch_pending",
        "prazo_inicial_intakes",
        ["dispatch_pending"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prazo_inicial_intakes_dispatch_pending",
        table_name="prazo_inicial_intakes",
    )
    op.drop_column("prazo_inicial_intakes", "dispatch_error_message")
    op.drop_column("prazo_inicial_intakes", "dispatched_at")
    op.drop_column("prazo_inicial_intakes", "dispatch_pending")
