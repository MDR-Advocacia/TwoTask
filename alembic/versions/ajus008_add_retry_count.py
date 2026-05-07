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

NOTA: criada originalmente com o id ajus006, colidindo com a outra
migration `ajus006_default_paused_true.py`. Renomeada pra ajus008 e
encadeada apos pin020 (ultima head valida) pra resolver o MultipleHeads
que travava o boot do container.

Revision ID: ajus008
Revises: pin020
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus008"
down_revision: Union[str, None] = "pin020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotente: a coluna pode ja existir no DB (foi aplicada via
    # ALTER TABLE manual durante a depuracao do fluxo classif). Nesse
    # caso, o boot do container so registra a versao no alembic sem
    # tentar recriar (evita "DuplicateColumn" e mantem a fila intacta).
    op.execute(
        "ALTER TABLE ajus_classificacao_queue "
        "ADD COLUMN IF NOT EXISTS retry_count integer "
        "NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ajus_classificacao_queue "
        "DROP COLUMN IF EXISTS retry_count"
    )
