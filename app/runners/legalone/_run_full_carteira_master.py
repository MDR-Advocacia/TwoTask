"""Script one-shot pra disparar varredura completa do Banco Master/Reu.

Rodar via:
    docker exec -d onetask-api-1 python /app/app/runners/legalone/_run_full_carteira_master.py

O `-d` faz o processo rodar em background; ele segue vivo mesmo quando o
docker exec retorna. Loga em /app/output/playwright/legalone/varredura-andamentos/run-full.log
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(
    "/app/output/playwright/legalone/varredura-andamentos/run-full.log"
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

logger = logging.getLogger("varredura.full-carteira-master")


def main() -> None:
    from app.db.session import SessionLocal
    from app.models.varredura import (
        QUEUE_STATUS_PENDING,
        RUN_STATUS_RUNNING,
        VarreduraProcessado,
        VarreduraRun,
    )
    from app.services.varredura.varredura_service import (
        VarreduraService,
        _run_subprocess_worker_impl,
    )

    db = SessionLocal()
    try:
        svc = VarreduraService(db)
        logger.info("Resolvendo lawsuit_ids do office 61 (Banco Master/Reu)...")
        ids, _ = svc._resolve_lawsuit_ids([61], max_total=None)
        logger.info("Resolvidos %s lawsuit_ids", len(ids))

        run = VarreduraRun(
            status=RUN_STATUS_RUNNING,
            started_at=datetime.now(timezone.utc),
            responsible_office_ids=[61],
            window_days=30,
            triggered_by="full-carteira-master",
            total_processos=len(ids),
        )
        db.add(run)
        db.flush()
        for lid in ids:
            db.add(
                VarreduraProcessado(
                    run_id=run.id,
                    lawsuit_id=lid,
                    queue_status=QUEUE_STATUS_PENDING,
                )
            )
        db.commit()
        logger.info(
            "Run #%s criada com %s processados. Iniciando subprocess Node...",
            run.id, len(ids),
        )
        _run_subprocess_worker_impl(db, run.id)
        logger.info("Run #%s concluida.", run.id)
    except Exception as exc:
        logger.exception("Falha catastrofica: %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
