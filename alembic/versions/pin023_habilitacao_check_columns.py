"""habilitacao_check: colunas de checagem heuristica do PDF de habilitacao

Revision ID: pin023
Revises: ufdbk001
Create Date: 2026-05-08

3 colunas em prazo_inicial_intakes:
- habilitacao_check_status: NAO_VERIFICADO|OK|ALERTA|FALHA|ERRO_EXTRACAO
- habilitacao_check_result: JSONB com lista de checks individuais
- habilitacao_check_at: timestamp da ultima validacao

Default NAO_VERIFICADO no servidor pra registros existentes — operador
2026-05-08 pediu pra IGNORAR habilitacoes antigas (sem batch retroativo);
quem precisar valida via botao "Revalidar" no painel.

Status FALHA nao bloqueia o avanco do intake — so sinaliza.
"""

from alembic import op
import sqlalchemy as sa


revision = "pin023"
down_revision = "ufdbk001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "habilitacao_check_status",
            sa.String(length=32),
            nullable=False,
            server_default="NAO_VERIFICADO",
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("habilitacao_check_result", sa.JSON(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "habilitacao_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_prazo_inicial_intakes_habilitacao_check_status",
        "prazo_inicial_intakes",
        ["habilitacao_check_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prazo_inicial_intakes_habilitacao_check_status",
        table_name="prazo_inicial_intakes",
    )
    op.drop_column("prazo_inicial_intakes", "habilitacao_check_at")
    op.drop_column("prazo_inicial_intakes", "habilitacao_check_result")
    op.drop_column("prazo_inicial_intakes", "habilitacao_check_status")
