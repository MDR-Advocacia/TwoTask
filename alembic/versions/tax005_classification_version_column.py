"""Adiciona taxonomy_version em classification_categories e classification_subcategories.

Permite distinguir cats/subs da v1 (legadas, seedadas pela tax001) das da
v2 (novas, com polo_scope 'ativo' ou 'passivo'). Engine de proposta de
tarefa, UI de templates e prompt do classificador filtram por essa coluna
em conjunto com o toggle global em app_settings (fase posterior).

Default 'v1' nos registros existentes — preserva todo o catalogo atual
como legacy. As cats v2 entram via tax006 com taxonomy_version='v2'.

Revision ID: tax005
Revises: tax004
"""

from typing import Sequence, Union

from alembic import op


revision: str = "tax005"
down_revision: Union[str, None] = "tax004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE classification_categories "
        "ADD COLUMN IF NOT EXISTS taxonomy_version varchar(8) "
        "NOT NULL DEFAULT 'v1'"
    )
    op.execute(
        "ALTER TABLE classification_subcategories "
        "ADD COLUMN IF NOT EXISTS taxonomy_version varchar(8) "
        "NOT NULL DEFAULT 'v1'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE classification_subcategories "
        "DROP COLUMN IF EXISTS taxonomy_version"
    )
    op.execute(
        "ALTER TABLE classification_categories "
        "DROP COLUMN IF EXISTS taxonomy_version"
    )
