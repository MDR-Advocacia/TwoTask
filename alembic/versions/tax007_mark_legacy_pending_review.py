"""Marca task_templates e office_classification_overrides existentes como
pendentes de revisao na taxonomia v2.

Fluxo desenhado com user em 2026-05-07: na transicao v1 -> v2, NENHUM
template e perdido. Cada registro v1 fica preservado com:

  - legacy_label = "<cat_v1> / <sub_v1>" (ou "<cat_v1>" se sub e NULL)
    -> mostrado no banner amarelo do modal de edicao pra que o operador
       saiba a qual classificacao o template referenciava antes.

  - needs_taxonomy_review = true
    -> engine de proposta de tarefa (apos fase 6) ignora o template ate
       o operador revisar e re-apontar pra cat/sub da v2 no modal.

is_active e DELIBERADAMENTE INTOCADO. O engine atual (publication_search_
service.py) filtra `TaskTemplate.is_active == True` mas NAO conhece
needs_taxonomy_review — entre o deploy desta migration e o deploy da
fase 6 (matcher polo-aware), os templates continuam casando como antes.
Quando a fase 6 sobe, o engine passa a filtrar tambem por
needs_taxonomy_review=False e os templates v1 viram dormentes
automaticamente, sem janela de quebra.

Idempotente: so processa registros com taxonomy_version='v1' AND
legacy_label IS NULL — rerun pula registros ja marcados.

Revision ID: tax007
Revises: tax006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax007"
down_revision: Union[str, None] = "tax006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # task_templates: marca todos os registros v1 nao-tratados como
    # pendentes. CONCAT_WS lida com subcategory NULL sem produzir NULL
    # no resultado (ao contrario de '||', que propaga NULL).
    conn.execute(sa.text("""
        UPDATE task_templates
           SET legacy_label = CONCAT_WS(' / ', category, subcategory),
               needs_taxonomy_review = true
         WHERE taxonomy_version = 'v1'
           AND legacy_label IS NULL
    """))

    # office_classification_overrides: mesmo tratamento.
    conn.execute(sa.text("""
        UPDATE office_classification_overrides
           SET legacy_label = CONCAT_WS(' / ', category, subcategory),
               needs_taxonomy_review = true
         WHERE taxonomy_version = 'v1'
           AND legacy_label IS NULL
    """))


def downgrade() -> None:
    """Reverte legacy_label e needs_taxonomy_review nos registros que
    tax007 marcou. is_active nao foi alterado no upgrade entao nao precisa
    ser tocado aqui."""
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE task_templates
           SET legacy_label = NULL,
               needs_taxonomy_review = false
         WHERE taxonomy_version = 'v1'
           AND legacy_label IS NOT NULL
    """))
    conn.execute(sa.text("""
        UPDATE office_classification_overrides
           SET legacy_label = NULL,
               needs_taxonomy_review = false
         WHERE taxonomy_version = 'v1'
           AND legacy_label IS NOT NULL
    """))
