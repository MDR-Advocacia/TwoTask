"""admin_notices: rastreio de impressao (views) + flag require_ack (pop-up)

Revision ID: not002_notice_views_and_ack
Revises: cit001
Create Date: 2026-06-17

Duas mudancas no modulo de avisos broadcast:

1) admin_notices.require_ack (Boolean, default false): quando true o aviso
   aparece como POP-UP bloqueante (modal) e so some quando o usuario clica
   "Ciente". False mantem o banner discreto no topo (comportamento atual).

2) admin_notice_views: nova tabela de IMPRESSAO. Registra quem teve o aviso
   renderizado na tela, independente de ter confirmado. PK (notice_id,
   user_id) -> idempotente. ON DELETE CASCADE nas duas FKs. Permite o painel
   admin mostrar "Visto por N" alem de "Confirmado por M".
"""

from alembic import op
import sqlalchemy as sa


revision = "not002_notice_views_and_ack"
down_revision = "cit001"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if _table_exists("admin_notices") and not _column_exists("admin_notices", "require_ack"):
        op.add_column(
            "admin_notices",
            sa.Column(
                "require_ack",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _table_exists("admin_notice_views"):
        op.create_table(
            "admin_notice_views",
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
                "first_seen_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_admin_notice_views_user",
            "admin_notice_views",
            ["user_id"],
        )


def downgrade() -> None:
    if _table_exists("admin_notice_views"):
        op.drop_index("ix_admin_notice_views_user", table_name="admin_notice_views")
        op.drop_table("admin_notice_views")
    if _column_exists("admin_notices", "require_ack"):
        op.drop_column("admin_notices", "require_ack")
