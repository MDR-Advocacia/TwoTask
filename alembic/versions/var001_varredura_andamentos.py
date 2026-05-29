"""var001: feature de varredura de andamentos.

Revision ID: var001
Revises: cla004
Create Date: 2026-05-19

Cria 3 tabelas pra varredura periodica de andamentos do L1 atras de
eventos relevantes (audiencia designada/cancelada, sentenca, revelia,
transito em julgado, arquivamento):

- varredura_run: 1 linha por execucao (operador clica "Nova varredura")
- varredura_processado: 1 linha por processo dentro da run (fila de
  trabalho — PENDENTE | PROCESSANDO | CONCLUIDO | FALHA)
- varredura_achado: 1 linha por evento detectado num andamento

Mesmo padrao da fila do Tratamento Web (status, attempt_count,
recover_zombies). Modulo novo, sem deploy em main — feature
incidental que roda local no docker.
"""

from alembic import op
import sqlalchemy as sa


revision = "var001"
down_revision = "cla004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "varredura_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="RUNNING",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "responsible_office_ids",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "window_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "total_processos",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_processados",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_achados",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_falhas",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("triggered_by", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_varredura_run_status",
        "varredura_run",
        ["status"],
    )

    op.create_table(
        "varredura_processado",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("varredura_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lawsuit_id", sa.Integer(), nullable=False),
        sa.Column("cnj_number", sa.String(64), nullable=True),
        sa.Column("office_id", sa.Integer(), nullable=True),
        sa.Column(
            "queue_status",
            sa.String(16),
            nullable=False,
            server_default="PENDENTE",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "total_andamentos_lidos",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_achados",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_reason", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_varredura_processado_run_status",
        "varredura_processado",
        ["run_id", "queue_status"],
    )
    op.create_index(
        "ix_varredura_processado_lawsuit_id",
        "varredura_processado",
        ["lawsuit_id"],
    )
    op.create_index(
        "ix_varredura_processado_cnj_number",
        "varredura_processado",
        ["cnj_number"],
    )

    op.create_table(
        "varredura_achado",
        sa.Column("id", sa.Integer(), primary_key=True),
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
        sa.Column("andamento_data", sa.Date(), nullable=True),
        sa.Column("andamento_hora", sa.String(8), nullable=True),
        sa.Column("andamento_tipo", sa.String(64), nullable=True),
        sa.Column("andamento_texto", sa.Text(), nullable=False),
        sa.Column("andamento_movimentado_por", sa.String(255), nullable=True),
        sa.Column("tipo_evento", sa.String(32), nullable=False),
        sa.Column("regex_matched", sa.Text(), nullable=True),
        sa.Column(
            "tratado",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("tratado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tratado_por", sa.String(255), nullable=True),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_varredura_achado_run_tipo",
        "varredura_achado",
        ["run_id", "tipo_evento"],
    )
    op.create_index(
        "ix_varredura_achado_run_tratado",
        "varredura_achado",
        ["run_id", "tratado"],
    )
    op.create_index(
        "ix_varredura_achado_lawsuit_id",
        "varredura_achado",
        ["lawsuit_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_varredura_achado_lawsuit_id", "varredura_achado")
    op.drop_index("ix_varredura_achado_run_tratado", "varredura_achado")
    op.drop_index("ix_varredura_achado_run_tipo", "varredura_achado")
    op.drop_table("varredura_achado")

    op.drop_index("ix_varredura_processado_cnj_number", "varredura_processado")
    op.drop_index("ix_varredura_processado_lawsuit_id", "varredura_processado")
    op.drop_index("ix_varredura_processado_run_status", "varredura_processado")
    op.drop_table("varredura_processado")

    op.drop_index("ix_varredura_run_status", "varredura_run")
    op.drop_table("varredura_run")
