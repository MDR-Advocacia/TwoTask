"""Versionamento da taxonomia em office_classification_overrides.

Mesmo tratamento de tax003, agora pros overrides por escritorio
(action='exclude' / 'include_custom'). Como os overrides referenciam
categoria/subcategoria por string literal, a transicao v1 -> v2 quebraria
silenciosamente sem essas flags — o override apontaria pro vazio.

Adiciona:
  - taxonomy_version (default 'v1')
  - legacy_label (Text nullable)
  - needs_taxonomy_review (default false)

Idem tax003, a migracao de dados (preencher os campos nos registros
existentes) acontece em migration separada apos o seed da v2.

Revision ID: tax004
Revises: tax003
"""

from typing import Sequence, Union

from alembic import op


revision: str = "tax004"
down_revision: Union[str, None] = "tax003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE office_classification_overrides "
        "ADD COLUMN IF NOT EXISTS taxonomy_version varchar(8) "
        "NOT NULL DEFAULT 'v1'"
    )
    op.execute(
        "ALTER TABLE office_classification_overrides "
        "ADD COLUMN IF NOT EXISTS legacy_label text"
    )
    op.execute(
        "ALTER TABLE office_classification_overrides "
        "ADD COLUMN IF NOT EXISTS needs_taxonomy_review boolean "
        "NOT NULL DEFAULT false"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_office_clf_overrides_pending_review "
        "ON office_classification_overrides (id) "
        "WHERE needs_taxonomy_review = true"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_office_clf_overrides_pending_review"
    )
    op.execute(
        "ALTER TABLE office_classification_overrides "
        "DROP COLUMN IF EXISTS needs_taxonomy_review"
    )
    op.execute(
        "ALTER TABLE office_classification_overrides "
        "DROP COLUMN IF EXISTS legacy_label"
    )
    op.execute(
        "ALTER TABLE office_classification_overrides "
        "DROP COLUMN IF EXISTS taxonomy_version"
    )
