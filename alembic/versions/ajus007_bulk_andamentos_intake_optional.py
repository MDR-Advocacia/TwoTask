"""permite ajus_andamento_queue.intake_id nullable (bulk upload sem intake)

Suporta upload em lote de andamentos AJUS (PDFs com CNJ no titulo OU
lista de CNJs sem arquivo) — fluxo manual do operador onde o item da
fila NAO origina de um intake de prazos iniciais. Nesses casos o
intake_id e' NULL e o item carrega o CNJ direto.

UNIQUE(intake_id) e' preservado: Postgres trata NULLs como distintos,
entao multiplos itens bulk com intake_id=NULL convivem com itens
auto-enfileirados com intake_id setado. Comportamento existente fica
intacto.

Revision ID: ajus007
Revises: pin019
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus007"
down_revision: Union[str, None] = "pin019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "ajus_andamento_queue",
        "intake_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Pra voltar pra NOT NULL precisa nao haver linhas com intake_id NULL.
    # Operador deve apagar/migrar essas linhas antes de rodar downgrade.
    op.alter_column(
        "ajus_andamento_queue",
        "intake_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
