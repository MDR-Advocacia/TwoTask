"""Adiciona estado de pausa global na fila de classificação AJUS.

Operador pode pausar o dispatcher pra parar de pegar novos batches sem
matar o que ja esta rodando (Playwright sincrono — interromper no meio
deixa storage_state inconsistente). Pausa eh reversivel via "Retomar".

Cancelamento de pendentes vira API separada que apenas marca todos os
itens em status=pendente como cancelado — nao precisa de coluna nova
porque ja temos `cancelado` na enum de status.

Colunas adicionadas em `ajus_classificacao_defaults`:
  - is_paused (bool, default false)
  - paused_at (timestamptz, nullable)
  - paused_by  (varchar 128, nullable) — login do operador que pausou

Revision ID: ajus004
Revises: ajus003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus004"
down_revision: Union[str, None] = "ajus003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ajus_classificacao_defaults") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_paused",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        batch_op.add_column(
            sa.Column(
                "paused_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        batch_op.add_column(
            sa.Column(
                "paused_by",
                sa.String(length=128),
                nullable=True,
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("ajus_classificacao_defaults") as batch_op:
        batch_op.drop_column("paused_by")
        batch_op.drop_column("paused_at")
        batch_op.drop_column("is_paused")
