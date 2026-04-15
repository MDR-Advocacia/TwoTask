"""Add scheduled automations and runs tables

Revision ID: aut001
Revises: usr001
Create Date: 2026-04-13 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aut001'
down_revision = 'usr001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create scheduled_automations table
    op.create_table(
        'scheduled_automations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('cron_expression', sa.String(), nullable=True),
        sa.Column('interval_minutes', sa.Integer(), nullable=True),
        sa.Column('office_ids', sa.JSON(), nullable=False),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['legal_one_users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scheduled_automations_created_by'), 'scheduled_automations', ['created_by'], unique=False)

    # Create scheduled_automation_runs table
    op.create_table(
        'scheduled_automation_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('automation_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('steps_executed', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['automation_id'], ['scheduled_automations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scheduled_automation_runs_automation_id'), 'scheduled_automation_runs', ['automation_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scheduled_automation_runs_automation_id'), table_name='scheduled_automation_runs')
    op.drop_table('scheduled_automation_runs')
    op.drop_index(op.f('ix_scheduled_automations_created_by'), table_name='scheduled_automations')
    op.drop_table('scheduled_automations')
