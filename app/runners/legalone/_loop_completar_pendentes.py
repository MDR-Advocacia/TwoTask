"""Loopa criando runs sucessivas pra cobrir os items pending das runs
anteriores ate zerar. Roda subprocess Node sincrono inline.

Uso:
    docker exec -d onetask-api-1 python //app/app/runners/legalone/_loop_completar_pendentes.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(
    "/app/output/playwright/legalone/varredura-andamentos/loop-completar.log"
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
logger = logging.getLogger("varredura.loop")

# Runs da feature (planilha-relatorios). Comeca em 16; novas runs criadas
# por este loop tambem sao consideradas.
PLANILHA_RUN_IDS_START = 16


def coletar_pending_de_todas_runs() -> tuple[set[int], set[int]]:
    """Retorna (lawsuits_ja_ok, lawsuits_pending) consolidando todas as
    runs da feature planilha-relatorios."""
    from app.db.session import SessionLocal
    from app.models.varredura import VarreduraRun

    base_dir = Path(
        "/app/output/playwright/legalone/varredura-andamentos"
    )
    db = SessionLocal()
    try:
        runs = (
            db.query(VarreduraRun)
            .filter(
                VarreduraRun.id >= PLANILHA_RUN_IDS_START,
                VarreduraRun.triggered_by.in_(
                    [
                        "planilha-relatorios-master",
                        "planilha-relatorios-complementar",
                        "planilha-relatorios-loop",
                    ]
                ),
            )
            .all()
        )
    finally:
        db.close()

    ja_ok: set[int] = set()
    pending: set[int] = set()
    for r in runs:
        sp = base_dir / f"run-{r.id}" / "status.json"
        if not sp.exists():
            continue
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in data.get("items") or []:
            lid = int(it.get("lawsuitId") or 0)
            if not lid:
                continue
            st = (it.get("status") or "").lower()
            if st == "ok":
                ja_ok.add(lid)
            elif st == "pending":
                pending.add(lid)
    # Items pending nao podem estar em ja_ok (priorizamos ok)
    pending -= ja_ok
    return ja_ok, pending


def criar_run_e_processar(pending: set[int]) -> int:
    """Cria run com os pending e roda subprocess sincrono. Retorna run_id."""
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

    CAPA_MAP_PATH = Path("/tmp/varredura-capa-map.json")
    capa_by_lawsuit = {}
    if CAPA_MAP_PATH.exists():
        capa_by_lawsuit = json.loads(CAPA_MAP_PATH.read_text(encoding="utf-8"))

    db = SessionLocal()
    try:
        run = VarreduraRun(
            status=RUN_STATUS_RUNNING,
            started_at=datetime.now(timezone.utc),
            responsible_office_ids=[],
            window_days=90,
            triggered_by="planilha-relatorios-loop",
            total_processos=len(pending),
        )
        db.add(run)
        db.flush()
        for lid in sorted(pending):
            cnj = None
            capa = capa_by_lawsuit.get(str(lid)) or {}
            cnj = capa.get("__cnj_original")
            db.add(
                VarreduraProcessado(
                    run_id=run.id,
                    lawsuit_id=lid,
                    cnj_number=cnj,
                    queue_status=QUEUE_STATUS_PENDING,
                )
            )
        db.commit()
        rid = run.id
        logger.info("Run #%s criada com %s pendentes. Rodando...", rid, len(pending))
        _run_subprocess_worker_impl(db, rid)
        logger.info("Run #%s concluida.", rid)
        return rid
    finally:
        db.close()


def main() -> None:
    MAX_ROUNDS = 10
    for rd in range(1, MAX_ROUNDS + 1):
        ja_ok, pending = coletar_pending_de_todas_runs()
        logger.info(
            "=== ROUND %s === ok=%s pending=%s",
            rd, len(ja_ok), len(pending),
        )
        if not pending:
            logger.info("Sem pendentes! Loop finalizado em %s rounds.", rd - 1)
            break
        rid = criar_run_e_processar(pending)
        # Da um respiro entre rounds (sessao OnePass)
        time.sleep(10)
    else:
        logger.warning("Atingido MAX_ROUNDS=%s sem zerar pendentes.", MAX_ROUNDS)

    logger.info("=== LOOP ENCERRADO ===")


if __name__ == "__main__":
    main()
