"""despacho de citacao + vinculada_master no intake (substitui patrocinio)

Revision ID: pin024
Revises: pub004_publication_task_audit
Create Date: 2026-06-22

Adiciona ao prazo_inicial_intakes:
- despacho_citacao_*: sinal-ancora do despacho que ORDENA a citacao da Re.
  Detectado de forma independente do bloco contestar; nao gera tarefa.
- vinculada_master_*: flag NEUTRA de vinculada Banco Master no polo passivo,
  substituindo a antiga analise de patrocinio (decisao/devolucao/corte por
  data — regra superada). A tabela prazo_inicial_patrocinio fica DORMANTE
  (historico preservado); nada eh dropado aqui.
"""
from alembic import op
import sqlalchemy as sa

revision = "pin024"
down_revision = "pub004_publication_task_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "despacho_citacao_existe",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("despacho_citacao_data", sa.Date(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("despacho_citacao_modalidade", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("despacho_citacao_efetivada", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("despacho_citacao_justificativa", sa.Text(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "vinculada_master_presente",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("vinculada_master_nome", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("vinculada_master_cnpj", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("vinculada_master_polo_confirmado", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("vinculada_master_observacao", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_prazo_inicial_intakes_despacho_citacao_existe",
        "prazo_inicial_intakes",
        ["despacho_citacao_existe"],
    )
    op.create_index(
        "ix_prazo_inicial_intakes_vinculada_master_presente",
        "prazo_inicial_intakes",
        ["vinculada_master_presente"],
    )


def downgrade():
    op.drop_index(
        "ix_prazo_inicial_intakes_vinculada_master_presente",
        table_name="prazo_inicial_intakes",
    )
    op.drop_index(
        "ix_prazo_inicial_intakes_despacho_citacao_existe",
        table_name="prazo_inicial_intakes",
    )
    for col in (
        "vinculada_master_observacao",
        "vinculada_master_polo_confirmado",
        "vinculada_master_cnpj",
        "vinculada_master_nome",
        "vinculada_master_presente",
        "despacho_citacao_justificativa",
        "despacho_citacao_efetivada",
        "despacho_citacao_modalidade",
        "despacho_citacao_data",
        "despacho_citacao_existe",
    ):
        op.drop_column("prazo_inicial_intakes", col)
