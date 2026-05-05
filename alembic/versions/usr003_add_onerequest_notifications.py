"""Add OneRequest error notification flag to users

Revision ID: usr003_onerequest_notifications
Revises: sqd003
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa


revision = "usr003_onerequest_notifications"
down_revision = "sqd003"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("legal_one_users", "notify_onerequest_errors"):
        op.add_column(
            "legal_one_users",
            sa.Column(
                "notify_onerequest_errors",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if _has_column("legal_one_users", "notify_onerequest_errors"):
        op.drop_column("legal_one_users", "notify_onerequest_errors")
