"""var002: tabela varredura_andamento_raw + capa_json em processado.

Revision ID: var002
Revises: var001
Create Date: 2026-06-07

Salva TODOS os andamentos brutos varridos (nao so' os que matcham regex)
pra permitir consultas livres (SQL + NDJSON export). Tambem adiciona
coluna `capa_json` em varredura_processado pra guardar snapshot da capa
da planilha (Listagem do L1) no momento da varredura.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "var002"
down_revision = "var001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Snapshot da capa por processado
    op.add_column(
        "varredura_processado",
        sa.Column("capa_json", postgresql.JSONB, nullable=True),
    )

    # 2) Andamentos brutos
    op.create_table(
        "varredura_andamento_raw",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("varredura_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processado_id",
            sa.Integer(),
            sa.ForeignKey("varredura_processado.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lawsuit_id", sa.Integer(), nullable=False),
        sa.Column("cnj_number", sa.String(64), nullable=True),
        sa.Column("office_id", sa.Integer(), nullable=True),
        sa.Column("andamento_data", sa.Date(), nullable=True),
        sa.Column("andamento_hora", sa.String(8), nullable=True),
        sa.Column("andamento_tipo", sa.String(64), nullable=True),
        sa.Column("andamento_texto", sa.Text(), nullable=False),
        sa.Column("andamento_movimentado_por", sa.String(255), nullable=True),
        sa.Column(
            "ordem",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Ordem na lista raspada (0 = mais recente)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_varredura_andamento_raw_lawsuit_id",
        "varredura_andamento_raw",
        ["lawsuit_id"],
    )
    op.create_index(
        "ix_varredura_andamento_raw_run_data",
        "varredura_andamento_raw",
        ["run_id", "andamento_data"],
    )
    op.create_index(
        "ix_varredura_andamento_raw_cnj",
        "varredura_andamento_raw",
        ["cnj_number"],
    )
    op.create_index(
        "ix_varredura_andamento_raw_tipo",
        "varredura_andamento_raw",
        ["andamento_tipo"],
    )
    op.create_index(
        "ix_varredura_andamento_raw_office_data",
        "varredura_andamento_raw",
        ["office_id", "andamento_data"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_varredura_andamento_raw_office_data", "varredura_andamento_raw"
    )
    op.drop_index("ix_varredura_andamento_raw_tipo", "varredura_andamento_raw")
    op.drop_index("ix_varredura_andamento_raw_cnj", "varredura_andamento_raw")
    op.drop_index(
        "ix_varredura_andamento_raw_run_data", "varredura_andamento_raw"
    )
    op.drop_index(
        "ix_varredura_andamento_raw_lawsuit_id", "varredura_andamento_raw"
    )
    op.drop_table("varredura_andamento_raw")
    op.drop_column("varredura_processado", "capa_json")
