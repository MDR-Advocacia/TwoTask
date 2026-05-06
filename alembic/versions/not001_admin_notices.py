"""admin_notices: avisos broadcast pra usuarios online (banner)

Revision ID: not001_admin_notices
Revises: pin019
Create Date: 2026-05-06

Tabelas:
- admin_notices: aviso (titulo, mensagem, severidade, janela starts_at..ends_at).
- admin_notice_dismissals: marca quem ja fechou — UNIQUE (notice_id, user_id)
  garante "so aparece uma vez por usuario". ON DELETE CASCADE em ambas
  as FKs pra excluir corretamente quando o aviso ou o usuario somem.

Filtragem de active no SQL: WHERE starts_at <= now() <= ends_at AND
NOT EXISTS dismissal — assim o aviso some pra todo mundo apos o ends_at,
mesmo pra quem nunca clicou no X.
"""

from alembic import op
import sqlalchemy as sa


revision = "not001_admin_notices"
down_revision = "pin019"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("admin_notices"):
        op.create_table(
            "admin_notices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            # severidade visual: info (azul), warning (amarelo), danger (vermelho)
            sa.Column(
                "severity",
                sa.String(length=16),
                nullable=False,
                server_default="info",
            ),
            sa.Column(
                "starts_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "ends_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "created_by_user_id",
                sa.Integer(),
                sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
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
        # Indice composto pra acelerar a query principal
        # WHERE starts_at <= now AND ends_at >= now.
        op.create_index(
            "ix_admin_notices_window",
            "admin_notices",
            ["starts_at", "ends_at"],
        )

    if not _table_exists("admin_notice_dismissals"):
        op.create_table(
            "admin_notice_dismissals",
            sa.Column(
                "notice_id",
                sa.Integer(),
                sa.ForeignKey("admin_notices.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("legal_one_users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "dismissed_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_admin_notice_dismissals_user",
            "admin_notice_dismissals",
            ["user_id"],
        )


def downgrade() -> None:
    if _table_exists("admin_notice_dismissals"):
        op.drop_index("ix_admin_notice_dismissals_user", table_name="admin_notice_dismissals")
        op.drop_table("admin_notice_dismissals")
    if _table_exists("admin_notices"):
        op.drop_index("ix_admin_notices_window", table_name="admin_notices")
        op.drop_table("admin_notices")
