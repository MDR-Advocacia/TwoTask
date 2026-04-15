"""add polo field to publication_record

Revision ID: pol001_polo_field
Revises: pbc001_pub_batch_clf
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "pol001_polo_field"
down_revision: Union[str, Sequence[str], None] = "pbc001_pub_batch_clf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "publicacao_registros",
        sa.Column("polo", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_publicacao_registros_polo",
        "publicacao_registros",
        ["polo"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publicacao_registros_polo",
        table_name="publicacao_registros",
    )
    op.drop_column("publicacao_registros", "polo")
