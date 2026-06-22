"""drop is_devolucao de ajus_cod_andamento (descontinua devolucao automatica)

Revision ID: ajus010
Revises: pin024
Create Date: 2026-06-22

Remove o campo `is_devolucao` + o partial unique index
`ux_ajus_cod_andamento_devolucao` (ambos criados no pin019). O fluxo de
devolucao automatica foi descontinuado: a regra de advogado pre-habilitado
/ devolucao foi superada (ver pin024 / vinculada_master). Os status
DEVOLUCAO_* do intake sao texto livre e ficam preservados para linhas
historicas — nada de schema muda do lado do intake.
"""
from alembic import op
import sqlalchemy as sa

revision = "ajus010"
down_revision = "pin024"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index(
        "ux_ajus_cod_andamento_devolucao",
        table_name="ajus_cod_andamento",
    )
    op.drop_column("ajus_cod_andamento", "is_devolucao")


def downgrade():
    op.add_column(
        "ajus_cod_andamento",
        sa.Column(
            "is_devolucao",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_ajus_cod_andamento_devolucao",
        "ajus_cod_andamento",
        ["is_devolucao"],
        unique=True,
        postgresql_where=sa.text("is_devolucao IS TRUE AND is_active IS TRUE"),
    )
