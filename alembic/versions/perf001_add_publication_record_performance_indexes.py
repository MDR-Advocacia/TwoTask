"""Performance: adiciona índices em publicacao_registros

Revision ID: perf001_pub_record_indexes
Revises: oli001_office_lawsuit_index
Create Date: 2026-04-16

Motivação
---------
Com uso por equipe (10+ usuários), ``/records/grouped`` e as listagens de
publicações começam a puxar seq scans em colunas frequentemente filtradas:
``linked_office_id``, ``creation_date``, ``publication_date``, ``is_duplicate``.

Além dos índices simples nessas colunas, criamos compostos para os padrões
de query mais comuns (listagem paginada por escritório+data e agrupamento
por processo filtrando is_duplicate).

Todas as criações são idempotentes via ``IF NOT EXISTS`` para suportar bancos
que já tenham alguns desses índices criados manualmente.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "perf001_pub_record_indexes"
down_revision: Union[str, Sequence[str], None] = "oli001_office_lawsuit_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index_name, columns) — cria na tabela publicacao_registros
_INDEXES: list[tuple[str, str]] = [
    ("ix_publicacao_registros_linked_office_id", "linked_office_id"),
    ("ix_publicacao_registros_creation_date", "creation_date"),
    ("ix_publicacao_registros_publication_date", "publication_date"),
    ("ix_publicacao_registros_is_duplicate", "is_duplicate"),
    ("ix_publicacao_registros_office_creation", "linked_office_id, creation_date"),
    ("ix_publicacao_registros_dup_creation", "is_duplicate, creation_date"),
    ("ix_publicacao_registros_status_dup", "status, is_duplicate"),
]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for name, cols in _INDEXES:
        if dialect == "postgresql":
            # IF NOT EXISTS é Postgres-only — mais seguro para bancos em produção
            # que possam ter recebido esses índices antes (ex: criados à mão).
            op.execute(
                f'CREATE INDEX IF NOT EXISTS {name} '
                f'ON publicacao_registros ({cols})'
            )
        else:
            # SQLite (dev local) — create_index cria normalmente; se já existir,
            # ignoramos o erro para não travar o ambiente.
            try:
                op.create_index(
                    name,
                    "publicacao_registros",
                    [c.strip() for c in cols.split(",")],
                )
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for name, _cols in reversed(_INDEXES):
        if dialect == "postgresql":
            op.execute(f'DROP INDEX IF EXISTS {name}')
        else:
            try:
                op.drop_index(name, table_name="publicacao_registros")
            except Exception:
                pass
