"""Add must_change_password field to legal_one_users

Revision ID: usr002
Revises: aut001
Create Date: 2026-04-14 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'usr002'
down_revision = 'aut001'
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return {c['name'] for c in inspector.get_columns(table_name)}
    except Exception:
        return set()


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    existing = _existing_columns('legal_one_users')

    if 'must_change_password' not in existing:
        op.add_column('legal_one_users', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    existing = _existing_columns('legal_one_users')
    if 'must_change_password' in existing:
        op.drop_column('legal_one_users', 'must_change_password')
