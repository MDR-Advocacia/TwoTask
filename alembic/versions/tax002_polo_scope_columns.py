"""Adiciona polo_scope em legal_one_offices e classification_categories.

Parte do redesenho da taxonomia de publicacoes (v2): cada escritorio passa
a declarar a qual polo do processo ele atende, e cada categoria/sub passa
a indicar a qual polo pertence. Combinados, permitem que a IA receba
APENAS a arvore aplicavel ao escritorio responsavel da publicacao.

Default 'ambos' preserva comportamento atual: enquanto a UI nao for usada
pra setar polos especificos, todo escritorio enxerga as duas arvores e
toda categoria fica visivel — fluxo identico ao v1.

Revision ID: tax002
Revises: ajus008
"""

from typing import Sequence, Union

from alembic import op


revision: str = "tax002"
down_revision: Union[str, None] = "ajus008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # legal_one_offices.polo_scope: define qual arvore (ativo/passivo/ambos)
    # esse escritorio enxerga em UI de templates e no prompt do classificador.
    op.execute(
        "ALTER TABLE legal_one_offices "
        "ADD COLUMN IF NOT EXISTS polo_scope varchar(16) "
        "NOT NULL DEFAULT 'ambos'"
    )

    # classification_categories.polo_scope: marca a qual polo a categoria
    # pertence na taxonomia v2. v1 (legada) fica como 'ambos' — registros
    # antigos continuam casando independente do polo do escritorio.
    op.execute(
        "ALTER TABLE classification_categories "
        "ADD COLUMN IF NOT EXISTS polo_scope varchar(16) "
        "NOT NULL DEFAULT 'ambos'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE classification_categories "
        "DROP COLUMN IF EXISTS polo_scope"
    )
    op.execute(
        "ALTER TABLE legal_one_offices "
        "DROP COLUMN IF EXISTS polo_scope"
    )
