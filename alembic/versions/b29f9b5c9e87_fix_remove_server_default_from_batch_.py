"""fix: remove server_default from batch_execution start_time

Revision ID: b29f9b5c9e87
Revises: f7eb76af776a
Create Date: 2025-11-06 09:29:09.973348

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b29f9b5c9e87'
down_revision: Union[str, Sequence[str], None] = 'f7eb76af776a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- INÍCIO DA CORREÇÃO: Força o Batch Mode ---
    # Usamos batch_alter_table que funciona no SQLite
    with op.batch_alter_table('lotes_execucao', schema=None) as batch_op:
        batch_op.alter_column('start_time',
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=None)
    # --- FIM DA CORREÇÃO ---


def downgrade() -> None:
    # --- INÍCIO DA CORREÇÃO: Força o Batch Mode ---
    # Também aplicamos no downgrade para consistência
    with op.batch_alter_table('lotes_execucao', schema=None) as batch_op:
        batch_op.alter_column('start_time',
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text('now()'))
    # --- FIM DA CORREÇÃO ---