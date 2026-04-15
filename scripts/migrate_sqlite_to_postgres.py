"""
Migração de dados: SQLite → PostgreSQL.

Uso (com o compose de pé):
    docker compose exec api python scripts/migrate_sqlite_to_postgres.py \
        --sqlite /app/data/database.db

Pré-requisitos:
    1. Postgres subiu (docker compose up -d postgres)
    2. `alembic upgrade head` já rodou no Postgres (schema criado)
    3. O arquivo .db está acessível no caminho informado

Estratégia: reflete tabelas do SQLite, lê em chunks e insere no Postgres
respeitando a ordem de FKs (tabelas sem dependência primeiro). Depois, ajusta
as sequences das PKs autoincrement do Postgres para o MAX(id)+1 de cada tabela.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate")

CHUNK = 500


def _topo_sort(md: MetaData) -> List[Table]:
    """Ordena tabelas respeitando FKs (parent antes de child)."""
    return list(md.sorted_tables)


def _truncate_pg(pg: Engine, tables: List[Table]) -> None:
    names = ", ".join(f'"{t.name}"' for t in tables)
    if not names:
        return
    with pg.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    log.info("Postgres: TRUNCATE em %d tabelas.", len(tables))


def _copy_table(src: Engine, dst: Engine, table: Table) -> int:
    total = 0
    with src.connect() as s_conn:
        rows_iter = s_conn.execution_options(stream_results=True).execute(select(table))
        batch = []
        with dst.begin() as d_conn:
            # Desabilita triggers de FK durante a cópia (SQLite não enforçava FK,
            # pode haver órfãos que reimportamos assim mesmo para preservar histórico).
            d_conn.execute(text("SET session_replication_role = 'replica'"))
            for row in rows_iter:
                batch.append(dict(row._mapping))
                if len(batch) >= CHUNK:
                    d_conn.execute(table.insert(), batch)
                    total += len(batch)
                    batch = []
            if batch:
                d_conn.execute(table.insert(), batch)
                total += len(batch)
            d_conn.execute(text("SET session_replication_role = 'origin'"))
    return total


def _fix_sequences(pg: Engine, tables: List[Table]) -> None:
    """Ajusta sequences do Postgres p/ MAX(id)+1 em cada tabela com PK int."""
    with pg.begin() as conn:
        for t in tables:
            pk_cols = [c for c in t.primary_key.columns]
            if len(pk_cols) != 1:
                continue
            pk = pk_cols[0]
            if not str(pk.type).lower().startswith(("integer", "bigint", "smallint")):
                continue
            seq_sql = text(
                "SELECT pg_get_serial_sequence(:tbl, :col)"
            )
            seq_name = conn.execute(seq_sql, {"tbl": t.name, "col": pk.name}).scalar()
            if not seq_name:
                continue
            max_sql = text(f'SELECT COALESCE(MAX("{pk.name}"), 0) FROM "{t.name}"')
            mx = conn.execute(max_sql).scalar() or 0
            conn.execute(text(f"SELECT setval('{seq_name}', :v)"), {"v": max(mx, 1)})
            log.info("sequence %s → %s", seq_name, mx)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sqlite", required=True, help="Caminho do arquivo .db SQLite")
    p.add_argument("--pg-url", default=os.getenv("DATABASE_URL"), help="URL Postgres destino")
    p.add_argument("--no-truncate", action="store_true", help="Não truncar Postgres antes")
    args = p.parse_args()

    if not args.pg_url or not args.pg_url.startswith("postgresql"):
        log.error("DATABASE_URL precisa ser postgresql://... (atual: %s)", args.pg_url)
        return 2
    if not os.path.exists(args.sqlite):
        log.error("SQLite não encontrado: %s", args.sqlite)
        return 2

    src = create_engine(f"sqlite:///{args.sqlite}")
    dst = create_engine(args.pg_url)

    src_md = MetaData()
    src_md.reflect(bind=src)
    dst_md = MetaData()
    dst_md.reflect(bind=dst)

    src_names = {t.name for t in src_md.tables.values()}
    dst_names = {t.name for t in dst_md.tables.values()}
    common = src_names & dst_names
    only_src = src_names - dst_names
    only_dst = dst_names - src_names

    if only_src:
        log.warning("Tabelas no SQLite ausentes no Postgres (serão ignoradas): %s", sorted(only_src))
    if only_dst:
        log.info("Tabelas novas no Postgres sem dados no SQLite (ok): %s", sorted(only_dst))

    # Usa o metadata do Postgres para obter a estrutura correta na inserção.
    pg_tables_sorted = [t for t in _topo_sort(dst_md) if t.name in common]
    log.info("Migrando %d tabelas em ordem topológica.", len(pg_tables_sorted))

    if not args.no_truncate:
        # Trunca em ordem inversa (filho antes de pai), CASCADE resolve.
        _truncate_pg(dst, list(reversed(pg_tables_sorted)))

    grand_total = 0
    for t in pg_tables_sorted:
        try:
            n = _copy_table(src, dst, t)
            grand_total += n
            log.info("✓ %s: %d linhas", t.name, n)
        except Exception as exc:
            log.error("✗ %s: %s", t.name, exc)
            raise

    log.info("Ajustando sequences...")
    _fix_sequences(dst, pg_tables_sorted)

    # Verificação alembic_version
    with dst.connect() as c:
        try:
            v = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
            log.info("alembic_version no Postgres: %s", v)
        except Exception:
            log.warning("Tabela alembic_version não encontrada — rode `alembic upgrade head` antes.")

    log.info("✅ Concluído. Total de linhas migradas: %d", grand_total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
