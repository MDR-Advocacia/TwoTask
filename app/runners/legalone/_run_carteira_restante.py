"""Script one-shot pra varrer o RESTANTE da carteira do office 61 em
lotes sequenciais. Pula lawsuit_ids ja' varridos em runs anteriores
(qualquer run em qualquer status, exceto FAILED).

Uso:
    docker exec -d onetask-api-1 python /app/app/runners/legalone/_run_carteira_restante.py [--batch-size 500]

Log: /app/output/playwright/legalone/varredura-andamentos/restante.log
XLSX por lote: /app/output/playwright/legalone/varredura-andamentos/run-{id}/varredura-{id}.xlsx
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(
    "/app/output/playwright/legalone/varredura-andamentos/restante.log"
)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("varredura.restante")


def main(office_id: int, batch_size: int) -> None:
    from app.db.session import SessionLocal
    from app.models.varredura import (
        QUEUE_STATUS_PENDING,
        RUN_STATUS_RUNNING,
        VarreduraProcessado,
        VarreduraRun,
    )
    from app.services.legal_one_client import LegalOneApiClient
    from app.services.varredura.varredura_service import (
        VarreduraService,
        _run_subprocess_worker_impl,
    )
    from app.api.v1.endpoints.varredura import _build_xlsx_payload

    # 1. Resolve TODOS os lawsuit_ids do office (pagina API L1)
    db = SessionLocal()
    try:
        svc = VarreduraService(db)
        logger.info("Resolvendo TODOS os lawsuit_ids do office %s...", office_id)
        all_ids, _ = svc._resolve_lawsuit_ids([office_id], max_total=None)
        logger.info("Office %s tem %s processos no total.", office_id, len(all_ids))

        # 2. Calcula processos JA' varridos (run anterior, qualquer status)
        already = {
            r[0]
            for r in (
                db.query(VarreduraProcessado.lawsuit_id)
                .distinct()
                .all()
            )
        }
        logger.info("Ja varridos em runs anteriores: %s", len(already))

        restante = sorted(set(all_ids) - already)
        logger.info("Restante pra varrer: %s processos", len(restante))

        if not restante:
            logger.info("Nada a fazer — restante vazio.")
            return

        # CNJs mapeados
        cnjs = svc._fetch_cnj_map(restante)

        # 3. Particiona em lotes
        total_lotes = (len(restante) + batch_size - 1) // batch_size
        logger.info(
            "Vai disparar %s lote(s) de ate %s processos cada.",
            total_lotes, batch_size,
        )

        for lote_idx in range(total_lotes):
            start = lote_idx * batch_size
            end = start + batch_size
            chunk = restante[start:end]
            logger.info(
                "─── Lote %s/%s: %s processos (offset %s..%s) ───",
                lote_idx + 1, total_lotes, len(chunk), start, end - 1,
            )

            # Cria run pra esse lote
            run = VarreduraRun(
                status=RUN_STATUS_RUNNING,
                started_at=datetime.now(timezone.utc),
                responsible_office_ids=[office_id],
                window_days=30,
                triggered_by=f"restante-master-lote-{lote_idx + 1}-de-{total_lotes}",
                total_processos=len(chunk),
            )
            db.add(run)
            db.flush()
            for lid in chunk:
                db.add(
                    VarreduraProcessado(
                        run_id=run.id,
                        lawsuit_id=lid,
                        cnj_number=cnjs.get(lid),
                        office_id=office_id,
                        queue_status=QUEUE_STATUS_PENDING,
                    )
                )
            db.commit()
            logger.info("Run #%s criada. Disparando subprocess...", run.id)

            try:
                _run_subprocess_worker_impl(db, run.id)
            except Exception as exc:
                logger.exception(
                    "Worker falhou no lote %s/%s (run #%s): %s",
                    lote_idx + 1, total_lotes, run.id, exc,
                )
                # Tenta proximo lote mesmo assim
                continue

            # 4. Gera XLSX do lote
            try:
                db.refresh(run)
                achados = run.achados
                processados = run.processados
                content = _build_xlsx_payload(
                    db, run=run, achados=achados, processados=processados,
                )
                xlsx_path = (
                    Path("/app/output/playwright/legalone/varredura-andamentos")
                    / f"run-{run.id}"
                    / f"varredura-{run.id}.xlsx"
                )
                xlsx_path.parent.mkdir(parents=True, exist_ok=True)
                xlsx_path.write_bytes(content)
                logger.info(
                    "Lote %s/%s OK: %s achados, XLSX em %s",
                    lote_idx + 1, total_lotes, len(achados), xlsx_path,
                )
            except Exception as exc:
                logger.exception("Falha gerando XLSX do lote %s: %s", lote_idx + 1, exc)

        logger.info("=== TODOS OS LOTES CONCLUIDOS ===")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--office-id", type=int, default=61)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    main(args.office_id, args.batch_size)
