"""cria prazo_inicial_pedidos (N:1 com intake)

Armazena pedidos extraídos pela IA da petição inicial — um registro
por pretensão da parte autora. Serve de base pra análise de
aprovisionamento (CPC 25) e classificação global de êxito (Bloco E).

Revision ID: pin009
Revises: pin008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pin009"
down_revision: Union[str, None] = "pin008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prazo_inicial_pedidos",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "intake_id",
            sa.Integer(),
            sa.ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tipo_pedido", sa.String(length=64), nullable=False),
        sa.Column("natureza", sa.String(length=64), nullable=True),
        sa.Column("valor_indicado", sa.Numeric(14, 2), nullable=True),
        sa.Column("valor_estimado", sa.Numeric(14, 2), nullable=True),
        sa.Column("fundamentacao_valor", sa.Text(), nullable=True),
        sa.Column("probabilidade_perda", sa.String(length=16), nullable=True),
        sa.Column("aprovisionamento", sa.Numeric(14, 2), nullable=True),
        sa.Column("fundamentacao_risco", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "probabilidade_perda IN ('remota', 'possivel', 'provavel')",
            name="ck_prazo_inicial_pedidos_prob_perda",
        ),
    )
    op.create_index(
        "ix_prazo_inicial_pedidos_intake_id",
        "prazo_inicial_pedidos",
        ["intake_id"],
    )
    op.create_index(
        "ix_prazo_inicial_pedidos_tipo_pedido",
        "prazo_inicial_pedidos",
        ["tipo_pedido"],
    )
    op.create_index(
        "ix_prazo_inicial_pedidos_probabilidade_perda",
        "prazo_inicial_pedidos",
        ["probabilidade_perda"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prazo_inicial_pedidos_probabilidade_perda",
        table_name="prazo_inicial_pedidos",
    )
    op.drop_index(
        "ix_prazo_inicial_pedidos_tipo_pedido",
        table_name="prazo_inicial_pedidos",
    )
    op.drop_index(
        "ix_prazo_inicial_pedidos_intake_id",
        table_name="prazo_inicial_pedidos",
    )
    op.drop_table("prazo_inicial_pedidos")
