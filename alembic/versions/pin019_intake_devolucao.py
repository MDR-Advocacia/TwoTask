"""adiciona is_devolucao em ajus_cod_andamento + status DEVOLUCAO no intake

Suporta o fluxo "intake de devolução": automação externa detecta que outro
advogado já está habilitado no Banco Master e manda um POST simplificado
em /prazos-iniciais/intake/devolucao com só CNJ + motivo opcional. O
sistema cria intake mínimo (sem capa/integra/PDF), marca patrocinio como
OUTRO_ESCRITORIO + suspeita_devolucao=true, e enfileira na fila AJUS
usando o cod_andamento marcado com `is_devolucao=true` (em vez do
default). Worker dispatch envia o andamento de devolução pra API AJUS.

- `is_devolucao`: análogo de `is_default` — só 1 cod_andamento ativo
  pode ter `is_devolucao=true` por vez (partial unique index).
- Status novos no intake (texto livre, sem enum coercitivo no DB):
    DEVOLUCAO_PENDENTE → registro criado, AJUS ainda não enviou
    DEVOLUCAO_ENVIADA  → worker dispatch confirmou sucesso

Revision ID: pin019
Revises: pin018
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "pin019"
down_revision: Union[str, None] = "pin018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ajus_cod_andamento",
        sa.Column(
            "is_devolucao",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    # Apenas um is_devolucao ATIVO por vez — partial unique index.
    op.create_index(
        "ux_ajus_cod_andamento_devolucao",
        "ajus_cod_andamento",
        ["is_devolucao"],
        unique=True,
        postgresql_where=sa.text("is_devolucao IS TRUE AND is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_ajus_cod_andamento_devolucao",
        table_name="ajus_cod_andamento",
    )
    op.drop_column("ajus_cod_andamento", "is_devolucao")
