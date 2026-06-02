"""Re-varre os 4170 processos da run #16 que ficaram em 'pending' no
status.json (subprocess Node morreu no meio). Cria run #17.

Uso:
    docker exec -d onetask-api-1 python //app/app/runners/legalone/_run_complementar_4170.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(
    "/app/output/playwright/legalone/varredura-andamentos/complementar-4170.log"
)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("varredura.complementar")


def main() -> None:
    from app.db.session import SessionLocal
    from app.models.varredura import (
        QUEUE_STATUS_PENDING,
        RUN_STATUS_RUNNING,
        VarreduraProcessado,
        VarreduraRun,
    )
    from app.services.varredura.varredura_service import (
        _run_subprocess_worker_impl,
    )

    # 1. Le os pendentes do status.json da run #16
    status_path = Path(
        "/app/output/playwright/legalone/varredura-andamentos/run-16/status.json"
    )
    data = json.loads(status_path.read_text(encoding="utf-8"))
    pendentes = []
    for it in data["items"]:
        if (it.get("status") or "").lower() == "pending":
            pendentes.append(
                {
                    "lawsuit_id": int(it["lawsuitId"]),
                    "cnj_number": it.get("cnjNumber") or None,
                }
            )
    logger.info("Pendentes encontrados na run #16: %s", len(pendentes))

    if not pendentes:
        logger.info("Nada a fazer.")
        return

    db = SessionLocal()
    try:
        # 2. Cria nova run pra esses pendentes
        run = VarreduraRun(
            status=RUN_STATUS_RUNNING,
            started_at=datetime.now(timezone.utc),
            responsible_office_ids=[],
            window_days=90,
            triggered_by="planilha-relatorios-complementar",
            total_processos=len(pendentes),
        )
        db.add(run)
        db.flush()
        for p in pendentes:
            db.add(
                VarreduraProcessado(
                    run_id=run.id,
                    lawsuit_id=p["lawsuit_id"],
                    cnj_number=p["cnj_number"],
                    queue_status=QUEUE_STATUS_PENDING,
                )
            )
        db.commit()
        logger.info(
            "Run #%s criada com %s pendentes. Disparando subprocess sincrono...",
            run.id, len(pendentes),
        )
        _run_subprocess_worker_impl(db, run.id)
        logger.info("Run #%s concluida.", run.id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
