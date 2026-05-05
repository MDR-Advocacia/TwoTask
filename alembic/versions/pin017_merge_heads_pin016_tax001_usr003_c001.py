"""merge heads pin016, tax001, usr003_onerequest_notifications

O alembic acumulou 3 heads paralelos depois do merge da feat/prazos-iniciais
com nosso worktree:
- pin016 (intake source/submitted_by/upload — esta branch)
- tax001 (classification taxonomy admin — main)
- usr003_onerequest_notifications (notify flag pra OneRequest — colega)

`c001_adiciona_tabela` parecia ser uma 4ª head mas é ancestral indireto
das 3 acima (via cadeia c001 → 3d256 → ... → sqd001 → ...). Incluí-la
explicitamente no merge causou KeyError no boot (alembic tenta remover
do head_set algo que não está lá).

Nenhum deles toca em tabelas em comum, então merge é seguro sem
upgrade/downgrade — apenas converge o grafo pra `alembic upgrade head`
voltar a funcionar.

Revision ID: pin017
Revises: pin016, tax001, usr003_onerequest_notifications
"""

from typing import Sequence, Union


revision: str = "pin017"
down_revision: Union[str, Sequence[str], None] = (
    "pin016",
    "tax001",
    "usr003_onerequest_notifications",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
