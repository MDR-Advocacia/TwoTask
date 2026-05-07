"""Versionamento da taxonomia em task_templates.

Adiciona 3 colunas pra suportar a transicao v1 -> v2 sem perder templates:

  - taxonomy_version (default 'v1'): marca em qual versao da taxonomia o
    template casa. Templates antigos continuam 'v1'; templates revisados
    pelo operador na UI nova viram 'v2'.

  - legacy_label (Text nullable): guarda "<categoria_v1> / <subcategoria_v1>"
    do registro original. Mostrado no banner amarelo do modal de edicao
    pra que o operador saiba a qual classificacao v1 esse template
    referenciava antes de escolher o equivalente na taxonomia nova.

  - needs_taxonomy_review (default false): flag que o engine de proposta
    de tarefa consulta — templates com flag=true sao ignorados ate o
    operador revisar. Garante que no go-live nenhum template fantasma
    case com classificacao errada.

A migracao de dados (preencher legacy_label, setar flags em todos os
registros existentes) acontece em migration separada (tax005) depois
do seed da taxonomia v2 estar no DB.

Revision ID: tax003
Revises: tax002
"""

from typing import Sequence, Union

from alembic import op


revision: str = "tax003"
down_revision: Union[str, None] = "tax002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE task_templates "
        "ADD COLUMN IF NOT EXISTS taxonomy_version varchar(8) "
        "NOT NULL DEFAULT 'v1'"
    )
    op.execute(
        "ALTER TABLE task_templates "
        "ADD COLUMN IF NOT EXISTS legacy_label text"
    )
    op.execute(
        "ALTER TABLE task_templates "
        "ADD COLUMN IF NOT EXISTS needs_taxonomy_review boolean "
        "NOT NULL DEFAULT false"
    )

    # Indice parcial: 99% das queries do painel "Templates Pendentes de
    # Revisao" filtram por needs_taxonomy_review=true. Index parcial e
    # barato em escrita (so atualiza quando a flag muda) e elimina
    # full scan quando o painel for aberto.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_templates_pending_review "
        "ON task_templates (id) "
        "WHERE needs_taxonomy_review = true"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_task_templates_pending_review"
    )
    op.execute(
        "ALTER TABLE task_templates DROP COLUMN IF EXISTS needs_taxonomy_review"
    )
    op.execute(
        "ALTER TABLE task_templates DROP COLUMN IF EXISTS legacy_label"
    )
    op.execute(
        "ALTER TABLE task_templates DROP COLUMN IF EXISTS taxonomy_version"
    )
