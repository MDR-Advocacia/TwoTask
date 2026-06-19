"""Add can_use_onerequest permission flag to users

Revision ID: usr004_can_use_onerequest
Revises: onr001_create_onerequest_tables
Create Date: 2026-06-19

Permissão dedicada de acesso ao módulo OneRequest. Default false: o módulo
entra TRAVADO — só admin enxerga (bypass no require_permission); o admin libera
por usuário na tela de Usuários & Permissões.
"""

from alembic import op
import sqlalchemy as sa


revision = "usr004_can_use_onerequest"
down_revision = "onr001_create_onerequest_tables"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("legal_one_users", "can_use_onerequest"):
        op.add_column(
            "legal_one_users",
            sa.Column(
                "can_use_onerequest",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if _has_column("legal_one_users", "can_use_onerequest"):
        op.drop_column("legal_one_users", "can_use_onerequest")
