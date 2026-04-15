"""Publication capture reliability: per-office cursor + fetch attempts

Revision ID: rel001
Revises: usr002
Create Date: 2026-04-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'rel001'
down_revision = 'usr002'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table('office_publication_cursor'):
        op.create_table(
            'office_publication_cursor',
            sa.Column('office_id', sa.Integer(), primary_key=True),
            sa.Column('last_successful_date', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_status', sa.String(), nullable=True),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if not _has_table('publication_fetch_attempt'):
        op.create_table(
            'publication_fetch_attempt',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('office_id', sa.Integer(), nullable=False, index=True),
            sa.Column('window_from', sa.DateTime(timezone=True), nullable=False),
            sa.Column('window_to', sa.DateTime(timezone=True), nullable=False),
            sa.Column('status', sa.String(), nullable=False),  # pending, success, failed, dead_letter
            sa.Column('attempt_n', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('records_found', sa.Integer(), nullable=True),
            sa.Column('automation_id', sa.Integer(), nullable=True, index=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_pfa_status_next_retry', 'publication_fetch_attempt', ['status', 'next_retry_at'])


def downgrade() -> None:
    if _has_table('publication_fetch_attempt'):
        op.drop_index('ix_pfa_status_next_retry', table_name='publication_fetch_attempt')
        op.drop_table('publication_fetch_attempt')
    if _has_table('office_publication_cursor'):
        op.drop_table('office_publication_cursor')
