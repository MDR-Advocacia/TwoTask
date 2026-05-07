"""merge heads pin021 (contestacao_existente) e ajus009 (classification_blocklist)

Os dois encadeiam apos ajus008 por caminhos paralelos:
- pin021 (contestacao_existente_intake) -> down: ajus008
- tax002..007 -> ajus009 (classification_blocklist) -> down: tax007 -> ... -> ajus008

Como nenhum dos dois caminhos toca tabelas em comum, esse merge e'
puramente de grafo (upgrade/downgrade vazios) -- so' converge as duas
heads em uma soh pra `alembic upgrade head` voltar a achar caminho
unico no boot do container.

Revision ID: pin022
Revises: pin021, ajus009
"""

from typing import Sequence, Union


revision: str = "pin022"
down_revision: Union[str, Sequence[str], None] = (
    "pin021",
    "ajus009",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
