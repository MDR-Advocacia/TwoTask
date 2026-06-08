"""Sync Postgres (varredura_andamento_raw + varredura_processado + varredura_run)
para DuckDB local em /app/output/analytics/varredura.duckdb.

Isolar dados analiticos do banco operacional do OneTask. O DuckDB:
  - arquivo unico, portavel (copia e analisa em qualquer lugar)
  - compressao columnar (~1GB pra 180d de 17k processos)
  - SQL completo + JSON nativo
  - sem servidor

Schema:
  run        (id PK, started_at, completed_at, status, office_id, window_days,
              triggered_by, total_processos, total_achados, total_falhas)
  processo   (lawsuit_id PK, cnj, office_id, run_id FK, queue_status,
              capa_json JSON, total_andamentos_lidos, total_achados,
              first_synced_at, last_synced_at)
  andamento  (id PK BIGINT, lawsuit_id, run_id, andamento_data DATE,
              andamento_hora, andamento_tipo, andamento_texto,
              andamento_movimentado_por, ordem, created_at)

Apos sync, opcionalmente apaga os mesmos dados do Postgres pra liberar
espaco (passar delete_after_sync=True).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DUCKDB_PATH = Path("/app/output/analytics/varredura.duckdb")


def _get_conn():
    import duckdb

    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DUCKDB_PATH))
    # Schema inicial (idempotente)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run (
            id INTEGER PRIMARY KEY,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            status VARCHAR,
            office_ids JSON,
            window_days INTEGER,
            triggered_by VARCHAR,
            total_processos INTEGER,
            total_achados INTEGER,
            total_falhas INTEGER,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS processo (
            lawsuit_id INTEGER PRIMARY KEY,
            cnj VARCHAR,
            office_id INTEGER,
            run_id INTEGER,
            queue_status VARCHAR,
            capa_json JSON,
            total_andamentos_lidos INTEGER,
            total_achados INTEGER,
            first_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS andamento (
            id BIGINT PRIMARY KEY,
            lawsuit_id INTEGER,
            run_id INTEGER,
            cnj_number VARCHAR,
            office_id INTEGER,
            andamento_data DATE,
            andamento_hora VARCHAR,
            andamento_tipo VARCHAR,
            andamento_texto VARCHAR,
            andamento_movimentado_por VARCHAR,
            ordem INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS ix_proc_office ON processo(office_id);
        CREATE INDEX IF NOT EXISTS ix_proc_run ON processo(run_id);
        CREATE INDEX IF NOT EXISTS ix_and_lawsuit ON andamento(lawsuit_id);
        CREATE INDEX IF NOT EXISTS ix_and_data ON andamento(andamento_data);
        CREATE INDEX IF NOT EXISTS ix_and_office_data ON andamento(office_id, andamento_data);
        CREATE INDEX IF NOT EXISTS ix_and_tipo ON andamento(andamento_tipo);
        """
    )
    return conn


def sync_run(run_id: int, delete_after_sync: bool = False) -> dict:
    """Sync 1 run do Postgres -> DuckDB. Idempotente (upsert).

    Args:
        run_id: id da varredura_run
        delete_after_sync: se True, apaga varredura_andamento_raw daquela
            run do Postgres apos confirmar sync (libera espaco).

    Returns:
        {"run_id", "processos_sincados", "andamentos_sincados", "deleted_from_pg"}
    """
    from app.db.session import SessionLocal
    from app.models.varredura import (
        VarreduraAndamentoRaw,
        VarreduraProcessado,
        VarreduraRun,
    )

    db = SessionLocal()
    conn = _get_conn()
    try:
        run = db.query(VarreduraRun).filter(VarreduraRun.id == run_id).first()
        if run is None:
            logger.warning("sync_run: run #%s nao existe", run_id)
            return {"run_id": run_id, "error": "not_found"}

        # 1) Run
        import json as _json
        conn.execute(
            """
            INSERT OR REPLACE INTO run
            (id, started_at, completed_at, status, office_ids, window_days,
             triggered_by, total_processos, total_achados, total_falhas, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                run.id,
                run.started_at,
                run.completed_at,
                run.status,
                _json.dumps(list(run.responsible_office_ids or [])),
                run.window_days,
                run.triggered_by,
                run.total_processos,
                run.total_achados,
                run.total_falhas,
            ],
        )

        # 2) Processados — upsert por lawsuit_id
        procs = (
            db.query(VarreduraProcessado)
            .filter(VarreduraProcessado.run_id == run_id)
            .all()
        )
        for p in procs:
            conn.execute(
                """
                INSERT OR REPLACE INTO processo
                (lawsuit_id, cnj, office_id, run_id, queue_status,
                 capa_json, total_andamentos_lidos, total_achados,
                 first_synced_at, last_synced_at)
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(
                        (SELECT first_synced_at FROM processo WHERE lawsuit_id = ?),
                        CURRENT_TIMESTAMP
                    ),
                    CURRENT_TIMESTAMP
                )
                """,
                [
                    p.lawsuit_id,
                    p.cnj_number,
                    p.office_id,
                    p.run_id,
                    p.queue_status,
                    _json.dumps(p.capa_json) if p.capa_json else None,
                    p.total_andamentos_lidos,
                    p.total_achados,
                    p.lawsuit_id,
                ],
            )

        # 3) Andamentos brutos (BIGINT id do Postgres como PK no DuckDB).
        # Pra deduplicar em re-sync, deletamos os da run antes (idempotente).
        conn.execute("DELETE FROM andamento WHERE run_id = ?", [run_id])
        ands = (
            db.query(VarreduraAndamentoRaw)
            .filter(VarreduraAndamentoRaw.run_id == run_id)
            .order_by(VarreduraAndamentoRaw.id)
            .all()
        )
        if ands:
            rows = [
                (
                    a.id,
                    a.lawsuit_id,
                    a.run_id,
                    a.cnj_number,
                    a.office_id,
                    a.andamento_data,
                    a.andamento_hora,
                    a.andamento_tipo,
                    a.andamento_texto,
                    a.andamento_movimentado_por,
                    a.ordem,
                    a.created_at,
                )
                for a in ands
            ]
            conn.executemany(
                """
                INSERT INTO andamento
                (id, lawsuit_id, run_id, cnj_number, office_id,
                 andamento_data, andamento_hora, andamento_tipo,
                 andamento_texto, andamento_movimentado_por,
                 ordem, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        deleted_pg = 0
        if delete_after_sync:
            # Apaga andamentos brutos do Postgres (libera espaco).
            # Processado/run continuam no Postgres (sao leves).
            result = (
                db.query(VarreduraAndamentoRaw)
                .filter(VarreduraAndamentoRaw.run_id == run_id)
                .delete(synchronize_session=False)
            )
            db.commit()
            deleted_pg = int(result or 0)
            logger.info(
                "sync_run #%s: deletou %s rows de andamento_raw do PG (sync confirmado em DuckDB)",
                run_id, deleted_pg,
            )

        out = {
            "run_id": run_id,
            "processos_sincados": len(procs),
            "andamentos_sincados": len(ands),
            "deleted_from_pg": deleted_pg,
        }
        logger.info("sync_run #%s OK: %s", run_id, out)
        return out
    finally:
        conn.close()
        db.close()


def sync_all_pending(delete_after_sync: bool = False) -> list[dict]:
    """Sync todas as runs DONE/FAILED que ainda nao foram syncadas
    (ou foram parcialmente). Compara contagens entre PG e DuckDB."""
    from app.db.session import SessionLocal
    from app.models.varredura import VarreduraAndamentoRaw, VarreduraRun
    from sqlalchemy import func as _f

    db = SessionLocal()
    conn = _get_conn()
    try:
        # Counts PG por run
        pg_counts = dict(
            db.query(
                VarreduraAndamentoRaw.run_id,
                _f.count(VarreduraAndamentoRaw.id),
            )
            .group_by(VarreduraAndamentoRaw.run_id)
            .all()
        )
        if not pg_counts:
            logger.info("Nenhum andamento bruto no PG pra sync.")
            return []

        # Counts DuckDB
        rows = conn.execute(
            "SELECT run_id, COUNT(*) FROM andamento GROUP BY run_id"
        ).fetchall()
        duck_counts = {r[0]: r[1] for r in rows}

        pendentes = [
            rid for rid, n in pg_counts.items()
            if duck_counts.get(rid, 0) != n
        ]
        logger.info("Runs pendentes de sync: %s", pendentes)
    finally:
        conn.close()
        db.close()

    results = []
    for rid in sorted(pendentes):
        results.append(sync_run(rid, delete_after_sync=delete_after_sync))
    return results


def get_db_size_mb() -> float:
    if not DUCKDB_PATH.exists():
        return 0.0
    return DUCKDB_PATH.stat().st_size / (1024 * 1024)
