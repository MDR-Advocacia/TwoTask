"""merge heads pin016, tax001, usr003_onerequest_notifications, c001_adiciona_tabela

O alembic acumulou 4 heads paralelos depois do merge da feat/prazos-iniciais
com nosso worktree:
- pin016 (intake source/submitted_by/upload — esta branch)
- tax001 (classification taxonomy admin — main)
- usr003_onerequest_notifications (notify flag pra OneRequest — colega)
- c001_adiciona_tabela (regras de co-ocorrência — cadeia antiga sem merge)

Nenhum deles toca em tabelas em comum, então merge é seguro sem
upgrade/downgrade — apenas converge o grafo pra `alembic upgrade head`
voltar a funcionar.

Revision ID: pin017
Revises: pin016, tax001, usr003_onerequest_notifications, c001_adiciona_tabela
"""

from typing import Sequence, Union


revision: str = "pin017"
down_revision: Union[str, Sequence[str], None] = (
    "pin016",
    "tax001",
    "usr003_onerequest_notifications",
    "c001_adiciona_tabela",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
