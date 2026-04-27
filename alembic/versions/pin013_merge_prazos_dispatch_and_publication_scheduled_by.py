"""merge heads pin012 e pub002

Revision ID: pin013
Revises: pin012, pub002
"""

from typing import Sequence, Union


revision: str = "pin013"
down_revision: Union[str, Sequence[str], None] = ("pin012", "pub002")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
