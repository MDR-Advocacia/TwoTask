"""Add user roles, permissions, and saved filters

Revision ID: usr001
Revises: feat002_clf_overrides
Create Date: 2026-04-13 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'usr001'
down_revision = 'feat002_clf_overrides'
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

    if 'role' not in existing:
        op.add_column('legal_one_users', sa.Column('role', sa.String(), nullable=False, server_default='user'))
    if 'can_schedule_batch' not in existing:
        op.add_column('legal_one_users', sa.Column('can_schedule_batch', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'can_use_publications' not in existing:
        op.add_column('legal_one_users', sa.Column('can_use_publications', sa.Boolean(), nullable=False, server_default=sa.true()))
    if 'default_office_id' not in existing:
        op.add_column('legal_one_users', sa.Column('default_office_id', sa.Integer(), nullable=True))

    # Note: FK on default_office_id intentionally omitted — SQLite does not support
    # ALTER TABLE ADD CONSTRAINT. FK is declared at the ORM level.

    if not _has_table('saved_filters'):
        op.create_table(
            'saved_filters',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('module', sa.String(), nullable=False),
            sa.Column('filters_json', sa.JSON(), nullable=False),
            sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['legal_one_users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_saved_filters_user_id'), 'saved_filters', ['user_id'], unique=False)


def downgrade() -> None:
    if _has_table('saved_filters'):
        op.drop_index(op.f('ix_saved_filters_user_id'), table_name='saved_filters')
        op.drop_table('saved_filters')

    existing = _existing_columns('legal_one_users')
    if 'default_office_id' in existing:
        op.drop_column('legal_one_users', 'default_office_id')
    if 'can_use_publications' in existing:
        op.drop_column('legal_one_users', 'can_use_publications')
    if 'can_schedule_batch' in existing:
        op.drop_column('legal_one_users', 'can_schedule_batch')
    if 'role' in existing:
        op.drop_column('legal_one_users', 'role')
