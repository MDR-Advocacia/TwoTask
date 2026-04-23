"""adiciona prazo fatal (sugestoes) e info de agravo (intakes)

Bloco C + Bloco B da evolução da taxonomia de Prazos Iniciais:

- Intake: +2 colunas (agravo_processo_origem_cnj, agravo_decisao_agravada_resumo)
- Sugestao: +3 colunas (prazo_fatal_data, prazo_fatal_fundamentacao, prazo_base_decisao)

Todas nullable — dados antigos ficam em branco; endpoint de reanalisar
(próximo bloco) repopula campos novos pra intakes já classificados.

Revision ID: pin008
Revises: pin007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pin008"
down_revision: Union[str, None] = "pin007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intake: info de agravo.
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("agravo_processo_origem_cnj", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("agravo_decisao_agravada_resumo", sa.Text(), nullable=True),
    )

    # Sugestao: prazo fatal + fundamentação.
    op.add_column(
        "prazo_inicial_sugestoes",
        sa.Column("prazo_fatal_data", sa.Date(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_sugestoes",
        sa.Column("prazo_fatal_fundamentacao", sa.Text(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_sugestoes",
        sa.Column("prazo_base_decisao", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prazo_inicial_sugestoes", "prazo_base_decisao")
    op.drop_column("prazo_inicial_sugestoes", "prazo_fatal_fundamentacao")
    op.drop_column("prazo_inicial_sugestoes", "prazo_fatal_data")
    op.drop_column("prazo_inicial_intakes", "agravo_decisao_agravada_resumo")
    op.drop_column("prazo_inicial_intakes", "agravo_processo_origem_cnj")
