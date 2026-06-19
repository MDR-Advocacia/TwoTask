"""OneRequest: cria a tabela onr_solicitacoes (DMIs do BB)

Revision ID: onr001_create_onerequest_tables
Revises: not002_notice_views_and_ack
Create Date: 2026-06-19

Fase 1 da integração do OneRequest pro Flow. Cria a tabela que recebe as DMIs
empurradas pelo motor RPA externo via /api/v1/onerequest/intake/*. Ver
docs/onerequest-integracao-plano.md.
"""

from alembic import op
import sqlalchemy as sa


revision = "onr001_create_onerequest_tables"
down_revision = "not002_notice_views_and_ack"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table)


def upgrade() -> None:
    if _has_table("onr_solicitacoes"):
        return

    op.create_table(
        "onr_solicitacoes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("numero_solicitacao", sa.String(), nullable=False),
        sa.Column("titulo", sa.String(), nullable=True),
        sa.Column("npj_direcionador", sa.String(), nullable=True),
        sa.Column("prazo", sa.String(), nullable=True),
        sa.Column("texto_dmi", sa.Text(), nullable=True),
        sa.Column("numero_processo", sa.String(), nullable=True),
        sa.Column("polo", sa.String(), nullable=True),
        sa.Column(
            "recebido_em",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("detalhe_capturado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status_sistema",
            sa.String(),
            server_default="ABERTO",
            nullable=False,
        ),
        sa.Column(
            "status_tratamento",
            sa.String(),
            server_default="NOVO",
            nullable=False,
        ),
        sa.Column("responsavel_user_id", sa.Integer(), nullable=True),
        sa.Column("setor", sa.String(), nullable=True),
        sa.Column("data_agendamento", sa.String(), nullable=True),
        sa.Column("anotacao", sa.Text(), nullable=True),
        sa.Column("created_task_id", sa.Integer(), nullable=True),
        sa.Column("linked_lawsuit_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scheduled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_by_email", sa.String(), nullable=True),
        sa.Column("scheduled_by_nome", sa.String(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["responsavel_user_id"],
            ["legal_one_users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_by_user_id"],
            ["legal_one_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_onr_solicitacoes_id", "onr_solicitacoes", ["id"], unique=False
    )
    op.create_index(
        "ix_onr_solicitacoes_numero_solicitacao",
        "onr_solicitacoes",
        ["numero_solicitacao"],
        unique=True,
    )
    op.create_index(
        "ix_onr_solicitacoes_npj_direcionador",
        "onr_solicitacoes",
        ["npj_direcionador"],
        unique=False,
    )
    op.create_index(
        "ix_onr_solicitacoes_numero_processo",
        "onr_solicitacoes",
        ["numero_processo"],
        unique=False,
    )
    op.create_index(
        "ix_onr_solicitacoes_status_sistema",
        "onr_solicitacoes",
        ["status_sistema"],
        unique=False,
    )
    op.create_index(
        "ix_onr_solicitacoes_status_tratamento",
        "onr_solicitacoes",
        ["status_tratamento"],
        unique=False,
    )
    op.create_index(
        "ix_onr_solicitacoes_responsavel_user_id",
        "onr_solicitacoes",
        ["responsavel_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_onr_solicitacoes_created_task_id",
        "onr_solicitacoes",
        ["created_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_onr_solicitacoes_linked_lawsuit_id",
        "onr_solicitacoes",
        ["linked_lawsuit_id"],
        unique=False,
    )


def downgrade() -> None:
    if not _has_table("onr_solicitacoes"):
        return
    op.drop_index("ix_onr_solicitacoes_linked_lawsuit_id", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_created_task_id", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_responsavel_user_id", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_status_tratamento", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_status_sistema", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_numero_processo", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_npj_direcionador", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_numero_solicitacao", table_name="onr_solicitacoes")
    op.drop_index("ix_onr_solicitacoes_id", table_name="onr_solicitacoes")
    op.drop_table("onr_solicitacoes")
