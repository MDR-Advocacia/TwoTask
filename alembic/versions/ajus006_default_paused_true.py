"""Inverte default do is_paused pra True (modo manual).

Antes: is_paused default=False -> worker processa automaticamente
quando ha itens pendentes + contas online. Operador inseria item via
intake/planilha e o robo ja saia rodando.

Depois: is_paused default=True -> default eh "parado". Itens vao pra
fila mas so processam quando o operador clica "Disparar pendentes",
que auto-despausa via endpoint /dispatch. Pra parar de novo, botao
"Pausar".

Esse comportamento eh mais previsivel pra operador que quer controlar
exatamente quando o robo gasta cota das contas AJUS / RAM da EC2.

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
    # 1. Atualiza server_default da coluna pra true
    with op.batch_alter_table("ajus_classificacao_defaults") as batch_op:
        batch_op.alter_column(
            "is_paused",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.text("true"),
        )

    # 2. Atualiza o registro singleton existente (id=1) pra paused=true.
    # Importante: deploys que ja tinham is_paused=false continuam assim
    # ate essa migracao rodar — depois disso ficam pausados ate operador
    # clicar "Disparar pendentes" pela primeira vez.
    op.execute(
        "UPDATE ajus_classificacao_defaults "
        "SET is_paused = true "
        "WHERE id = 1 AND is_paused = false"
    )


def downgrade() -> None:
    with op.batch_alter_table("ajus_classificacao_defaults") as batch_op:
        batch_op.alter_column(
            "is_paused",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.text("false"),
        )
    # Nao reverte o estado dos registros — operador pode estar usando
    # o estado pausado intencionalmente.
