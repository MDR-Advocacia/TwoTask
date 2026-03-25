"""feat: add legal_one_task_subtypes table

Revision ID: eb2500839a91
Revises: a00000000000
Create Date: 2025-10-02 12:33:00.608836

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb2500839a91'
down_revision: Union[str, Sequence[str], None] = 'a00000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'legal_one_task_subtypes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('parent_type_external_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['parent_type_external_id'], ['legal_one_task_types.external_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_legal_one_task_subtypes_external_id'), 'legal_one_task_subtypes', ['external_id'], unique=True)
    op.create_index(op.f('ix_legal_one_task_subtypes_id'), 'legal_one_task_subtypes', ['id'], unique=False)
    op.create_index(
        op.f('ix_legal_one_task_subtypes_parent_type_external_id'),
        'legal_one_task_subtypes',
        ['parent_type_external_id'],
        unique=False,
    )

    # The initial schema created an index for `parent_id`. Drop it before
    # recreating the SQLite table without that legacy column.
    op.drop_index(op.f('ix_legal_one_task_types_parent_id'), table_name='legal_one_task_types')

    with op.batch_alter_table('legal_one_task_types', schema=None) as batch_op:
        batch_op.drop_column('parent_id')


def downgrade() -> None:
    with op.batch_alter_table('legal_one_task_types', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.INTEGER(), nullable=True))
        batch_op.create_foreign_key(None, 'legal_one_task_types', ['parent_id'], ['id'])
    op.create_index(op.f('ix_legal_one_task_types_parent_id'), 'legal_one_task_types', ['parent_id'], unique=False)

    with op.batch_alter_table('legal_one_task_subtypes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_legal_one_task_subtypes_parent_type_external_id'))
        batch_op.drop_index(batch_op.f('ix_legal_one_task_subtypes_id'))
        batch_op.drop_index(batch_op.f('ix_legal_one_task_subtypes_external_id'))

    op.drop_table('legal_one_task_subtypes')
