"""merge heads ajus007 e not001_admin_notices

Os dois foram criados em paralelo a partir de pin019:
- ajus007 (bulk upload de andamentos AJUS com intake_id nullable)
- not001_admin_notices (avisos broadcast pra usuarios online)

Nenhum dos dois fechou pro outro no momento do merge pra main, entao
o `alembic upgrade head` quebrou no boot do container com MultipleHeads.
Nenhum dos dois toca tabelas em comum, entao merge e' seguro sem
upgrade/downgrade — apenas converge o grafo.

Revision ID: pin020
Revises: ajus007, not001_admin_notices
"""

from typing import Sequence, Union


revision: str = "pin020"
down_revision: Union[str, Sequence[str], None] = (
    "ajus007",
    "not001_admin_notices",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
