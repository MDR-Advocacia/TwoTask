"""OneRequest: tabela de anotações (log de auditoria por DMI)

Revision ID: onr002_anotacoes
Revises: usr004_can_use_onerequest
Create Date: 2026-06-19

Log append-only de anotações por solicitação (quem escreveu, quando, texto) —
ex.: "usuário respondeu atrasado em tal data". Ver §8 do plano.
"""

from alembic import op
import sqlalchemy as sa


revision = "onr002_anotacoes"
down_revision = "usr004_can_use_onerequest"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table)


def upgrade() -> None:
    if _has_table("onr_anotacoes"):
        return
    op.create_table(
        "onr_anotacoes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitacao_id", sa.Integer(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("autor_user_id", sa.Integer(), nullable=True),
        sa.Column("autor_nome", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["solicitacao_id"], ["onr_solicitacoes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["autor_user_id"], ["legal_one_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_onr_anotacoes_id", "onr_anotacoes", ["id"], unique=False)
    op.create_index(
        "ix_onr_anotacoes_solicitacao_id", "onr_anotacoes", ["solicitacao_id"], unique=False
    )


def downgrade() -> None:
    if not _has_table("onr_anotacoes"):
        return
    op.drop_index("ix_onr_anotacoes_solicitacao_id", table_name="onr_anotacoes")
    op.drop_index("ix_onr_anotacoes_id", table_name="onr_anotacoes")
    op.drop_table("onr_anotacoes")
