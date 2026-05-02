"""merge heads pin014 e ajus006

O alembic acumulou 2 heads paralelos:
- pin014 (template no-op em prazo_inicial_task_templates)
- ajus006 (default paused=true em ajus_classificacao_config)

Os dois mexem em tabelas distintas — sem conflito real, so precisa
do merge node pra alembic.upgrade head saber pra onde ir.

Revision ID: pin015
Revises: pin014, ajus006
"""

from typing import Sequence, Union


revision: str = "pin015"
down_revision: Union[str, Sequence[str], None] = ("pin014", "ajus006")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
