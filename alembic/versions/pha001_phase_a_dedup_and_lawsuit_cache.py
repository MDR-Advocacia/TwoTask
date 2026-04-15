"""Phase A: dedup por (lawsuit_id, publication_date) + lawsuit_cache

Revision ID: pha001
Revises: rel001
Create Date: 2026-04-14 18:00:00.000000

Objetivos:
  1. Criar tabela `lawsuit_cache` para reduzir chamadas a /Lawsuits (TTL 24h).
  2. Backfill: marcar duplicatas pré-existentes em publicacao_registros
     (mesmo linked_lawsuit_id + publication_date) com status
     'DESCARTADO_DUPLICADA' — mantendo apenas o registro de menor id.
  3. Criar índice único parcial `uq_pub_lawsuit_date` em
     publicacao_registros(linked_lawsuit_id, publication_date) restrito aos
     registros "vivos" (não descartados/ignorados) com ambos os campos
     preenchidos. Serve como garantia de integridade para a guarda de
     ingestão em app-level.
"""
from alembic import op
import sqlalchemy as sa


revision = 'pha001'
down_revision = 'rel001'
branch_labels = None
depends_on = None


STATUS_DISCARDED = 'DESCARTADO_DUPLICADA'


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(idx.get('name') == index_name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    # 1) lawsuit_cache ───────────────────────────────────────────────
    if not _has_table('lawsuit_cache'):
        op.create_table(
            'lawsuit_cache',
            sa.Column('lawsuit_id', sa.Integer(), primary_key=True),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column(
                'fetched_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            'ix_lawsuit_cache_fetched_at',
            'lawsuit_cache',
            ['fetched_at'],
        )

    # 2) Backfill de duplicatas em publicacao_registros ──────────────
    # Mantém o menor id de cada grupo (lawsuit_id, publication_date) e
    # marca os demais como DESCARTADO_DUPLICADA + is_duplicate=true.
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        bind.execute(sa.text(f"""
            UPDATE publicacao_registros AS r
            SET status = :st, is_duplicate = TRUE
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY linked_lawsuit_id, publication_date
                           ORDER BY id ASC
                       ) AS rn
                FROM publicacao_registros
                WHERE linked_lawsuit_id IS NOT NULL
                  AND publication_date IS NOT NULL
                  AND publication_date <> ''
                  AND COALESCE(is_duplicate, FALSE) = FALSE
            ) AS ranked
            WHERE ranked.id = r.id
              AND ranked.rn > 1
        """), {"st": STATUS_DISCARDED})
    else:
        # SQLite / outros — fallback simples
        bind.execute(sa.text(f"""
            UPDATE publicacao_registros
            SET status = :st, is_duplicate = 1
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY linked_lawsuit_id, publication_date
                               ORDER BY id ASC
                           ) AS rn
                    FROM publicacao_registros
                    WHERE linked_lawsuit_id IS NOT NULL
                      AND publication_date IS NOT NULL
                      AND publication_date <> ''
                      AND COALESCE(is_duplicate, 0) = 0
                ) ranked
                WHERE rn > 1
            )
        """), {"st": STATUS_DISCARDED})

    # 3) Índice único parcial ────────────────────────────────────────
    # Só aplica sobre registros "vivos" (não descartados) com ambos os campos.
    if not _has_index('publicacao_registros', 'uq_pub_lawsuit_date'):
        if dialect == 'postgresql':
            op.execute(f"""
                CREATE UNIQUE INDEX uq_pub_lawsuit_date
                ON publicacao_registros (linked_lawsuit_id, publication_date)
                WHERE linked_lawsuit_id IS NOT NULL
                  AND publication_date IS NOT NULL
                  AND publication_date <> ''
                  AND status <> '{STATUS_DISCARDED}'
                  AND COALESCE(is_duplicate, FALSE) = FALSE
            """)
        else:
            # SQLite 3.8+ também suporta partial indexes
            op.execute(f"""
                CREATE UNIQUE INDEX uq_pub_lawsuit_date
                ON publicacao_registros (linked_lawsuit_id, publication_date)
                WHERE linked_lawsuit_id IS NOT NULL
                  AND publication_date IS NOT NULL
                  AND publication_date <> ''
                  AND status <> '{STATUS_DISCARDED}'
                  AND COALESCE(is_duplicate, 0) = 0
            """)


def downgrade() -> None:
    if _has_index('publicacao_registros', 'uq_pub_lawsuit_date'):
        op.drop_index('uq_pub_lawsuit_date', table_name='publicacao_registros')

    # Não desfaz o backfill — é seguro manter os registros marcados.

    if _has_table('lawsuit_cache'):
        if _has_index('lawsuit_cache', 'ix_lawsuit_cache_fetched_at'):
            op.drop_index('ix_lawsuit_cache_fetched_at', table_name='lawsuit_cache')
        op.drop_table('lawsuit_cache')
