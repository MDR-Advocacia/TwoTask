"""user_feedbacks: feedback livre dos usuarios pra equipe (botao flutuante)

Revision ID: ufdbk001_user_feedbacks
Revises: tax009_seed_template_driven_setting
Create Date: 2026-05-08

Tabela:
- user_feedbacks: feedback enviado pelo botao flutuante presente em
  todas as paginas autenticadas. Categorizado (bug/sugestao/duvida/
  elogio/outro) e com captura automatica de page_url + user_agent pra
  ajudar o admin a reproduzir bugs sem precisar pedir contexto.

Status:
- "novo"      — recem-chegado, ainda nao olhado
- "lido"      — admin abriu o detalhe (so muda quando o admin marca)
- "arquivado" — admin terminou de tratar, esconde da lista padrao

Indices:
- ix_user_feedbacks_status_created (status, created_at desc) — acelera
  o caso comum de "listar novos por ordem cronologica reversa".
"""

from alembic import op
import sqlalchemy as sa


revision = "ufdbk001_user_feedbacks"
down_revision = "tax009_seed_template_driven_setting"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("user_feedbacks"):
        return

    op.create_table(
        "user_feedbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # categoria livre da UI (bug/sugestao/duvida/elogio/outro). String
        # em vez de enum pra evitar migration toda vez que adicionar nova
        # categoria — a UI valida o set.
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        # captura automatica do contexto pra reproducao de bugs.
        sa.Column("page_url", sa.String(length=500), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        # ciclo de vida do feedback no painel admin.
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="novo",
        ),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_feedbacks_status_created",
        "user_feedbacks",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_user_feedbacks_user",
        "user_feedbacks",
        ["user_id"],
    )


def downgrade() -> None:
    if not _table_exists("user_feedbacks"):
        return
    op.drop_index("ix_user_feedbacks_user", table_name="user_feedbacks")
    op.drop_index("ix_user_feedbacks_status_created", table_name="user_feedbacks")
    op.drop_table("user_feedbacks")
