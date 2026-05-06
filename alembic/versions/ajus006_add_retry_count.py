"""Adiciona retry_count na fila AJUS pra reenfileirar erros transitorios.

Erros tipicos do RPA AJUS sao timing-issues que retentar resolve:
  - "AJUS nao liberou workspace dentro do timeout" (sessao precisa
    re-init, comum apos rebuild ou pausa longa)
  - "Nao consegui selecionar 'X' no campo Y (combobox ExtJS)" (store
    nao carregou a tempo)
  - "Campo dependente 'Comarca' nao ficou visivel" (UF firmou mas
    Comarca ainda renderizando)
  - "Nao foi possivel localizar a busca rapida" (workspace lazy)

Esses erros NAO devem virar 'erro' definitivo no primeiro try — ficam
travando a fila ate operador dar retry manual. Com retry_count,
voltam pra `pendente` automaticamente ate atingir limite (5x).

Revision ID: ajus006
Revises: ajus005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus006"
down_revision: Union[str, None] = "ajus005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ajus_classificacao_queue",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("ajus_classificacao_queue", "retry_count")
