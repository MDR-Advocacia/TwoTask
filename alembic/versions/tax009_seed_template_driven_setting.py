"""Seed do setting `template_driven_taxonomy` em app_settings.

Default 'true' — ativa o modo arvore enxuta (cats sem template do
escritorio nao aparecem no prompt da IA, exceto residuais "Para Analise"
via whitelist).

Decisao consolidada com user em 2026-05-07 (fase 13): mais elegante
que manter overrides exclude por escritorio. Operador so configura
templates; arvore aplicavel se autorregula.

Revision ID: tax009
Revises: tax008
"""

from typing import Sequence, Union

from alembic import op


revision: str = "tax009"
down_revision: Union[str, None] = "tax008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotente: se a key ja existe (operador rodou tax009 e depois
    # mudou pra 'false' via Admin), o ON CONFLICT preserva a escolha.
    op.execute("""
        INSERT INTO app_settings (key, value, description)
        VALUES (
            'template_driven_taxonomy',
            'true',
            'Quando true, a arvore aplicavel a um escritorio so inclui categorias com pelo menos um template ativo do escritorio (ou global). Cats residuais "Para Analise" sempre aparecem via whitelist. Default true desde tax009.'
        )
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Remove a setting — proximo boot do app vai usar default True
    # (definido em app/services/classifier/taxonomy.py:is_template_driven_taxonomy_active).
    op.execute("DELETE FROM app_settings WHERE key = 'template_driven_taxonomy'")
