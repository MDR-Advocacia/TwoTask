"""feat: adiciona tabela para regras de co-ocorrência de tarefas

Revision ID: c001_adiciona_tabela
Revises: b840aa96d487
Create Date: 2025-10-14 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c001_adiciona_tabela'
down_revision: Union[str, None] = 'b840aa96d487'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    print("Executando migração para CRIAR a tabela 'task_corequisite_rules'...")
    op.create_table('task_corequisite_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('primary_subtype_id', sa.Integer(), nullable=False),
        sa.Column('secondary_subtype_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(), nullable=True, comment="Descrição da regra. Ex: 'Audiência sempre requer Preposto.'"),
        sa.ForeignKeyConstraint(['primary_subtype_id'], ['legal_one_task_subtypes.id'], ),
        sa.ForeignKeyConstraint(['secondary_subtype_id'], ['legal_one_task_subtypes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_corequisite_rules_id'), 'task_corequisite_rules', ['id'], unique=False)
    print("Tabela 'task_corequisite_rules' criada com sucesso.")


def downgrade() -> None:
    op.drop_index(op.f('ix_task_corequisite_rules_id'), table_name='task_corequisite_rules')
    op.drop_table('task_corequisite_rules')