"""adiciona agregados globais ao prazo_inicial_intakes

Campos computados a partir de prazo_inicial_pedidos (Bloco E):
- valor_total_pedido: soma dos valor_indicado dos pedidos
- valor_total_estimado: soma dos valor_estimado
- aprovisionamento_sugerido: soma dos aprovisionamento (CPC 25)
- probabilidade_exito_global: "menos favorável" (inverso do pior
  prob_perda entre pedidos)
- analise_estrategica: texto livre da IA explicando a classificação

Todas NULL — hidratadas no classify ou via reanalisar (Bloco F).

Revision ID: pin010
Revises: pin009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pin010"
down_revision: Union[str, None] = "pin009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("valor_total_pedido", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("valor_total_estimado", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("aprovisionamento_sugerido", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("probabilidade_exito_global", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("analise_estrategica", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prazo_inicial_intakes", "analise_estrategica")
    op.drop_column("prazo_inicial_intakes", "probabilidade_exito_global")
    op.drop_column("prazo_inicial_intakes", "aprovisionamento_sugerido")
    op.drop_column("prazo_inicial_intakes", "valor_total_estimado")
    op.drop_column("prazo_inicial_intakes", "valor_total_pedido")
