"""Script one-shot pra disparar varredura PRIORITARIA a partir do TXT.

Le /tmp/basescrapping-prioritaria.txt (1 CNJ por linha), resolve
lawsuit_ids via API L1, cria a run manualmente (sem usar thread daemon)
e roda subprocess Node SINCRONO inline — assim o script fica vivo enquanto
o Playwright roda, e o `docker exec -d` mantem o processo em background.

Uso:
    docker cp local-list.txt onetask-api-1:/tmp/basescrapping-prioritaria.txt
    docker exec -d onetask-api-1 python /app/app/runners/legalone/_run_prioritaria.py

Log: /app/output/playwright/legalone/varredura-andamentos/run-prioritaria.log
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

INPUT_PATH = Path("/tmp/basescrapping-prioritaria.txt")
LOG_PATH = Path(
    "/app/output/playwright/legalone/varredura-andamentos/run-prioritaria.log"
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
logger = logging.getLogger("varredura.prioritaria")


def main() -> None:
    from app.db.session import SessionLocal
    from app.models.varredura import (
        QUEUE_STATUS_PENDING,
        RUN_STATUS_RUNNING,
        VarreduraProcessado,
        VarreduraRun,
    )
    from app.services.legal_one_client import LegalOneApiClient
    from app.services.varredura.varredura_service import (
        _run_subprocess_worker_impl,
    )

    if not INPUT_PATH.exists():
        logger.error("Input nao encontrado: %s", INPUT_PATH)
        raise SystemExit(1)

    # 1. Le e normaliza CNJs (so digitos)
    cnjs_raw: list[str] = []
    seen: set[str] = set()
    for line in INPUT_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 15 and digits not in seen:
            cnjs_raw.append(digits)
            seen.add(digits)
    logger.info("Lidos %s CNJs unicos do arquivo.", len(cnjs_raw))

    if not cnjs_raw:
        logger.error("Arquivo sem CNJs validos.")
        raise SystemExit(1)

    # 2. Resolve CNJs -> lawsuit_ids via API L1
    db = SessionLocal()
    try:
        client = LegalOneApiClient()
        logger.info("Resolvendo %s CNJs via API L1 (pode demorar)...", len(cnjs_raw))
        matches = client.search_lawsuits_by_cnj_numbers(cnjs_raw)
        logger.info("API L1 retornou %s matches.", len(matches))

        cnj_to_id: dict[str, int] = {}
        for cnj_norm in cnjs_raw:
            payload = None
            for k, v in matches.items():
                if "".join(ch for ch in str(k) if ch.isdigit()) == cnj_norm:
                    payload = v
                    break
            if payload is None:
                continue
            pid = payload.get("id")
            if pid is not None:
                try:
                    cnj_to_id[cnj_norm] = int(pid)
                except (TypeError, ValueError):
                    pass

        unresolved = [c for c in cnjs_raw if c not in cnj_to_id]
        logger.info(
            "Resolvidos: %s / %s (unresolved: %s)",
            len(cnj_to_id), len(cnjs_raw), len(unresolved),
        )
        if unresolved:
            logger.warning(
                "Primeiros 5 nao resolvidos: %s",
                ", ".join(unresolved[:5]),
            )

        if not cnj_to_id:
            logger.error("Nenhum CNJ resolvido — abortando.")
            raise SystemExit(1)

        # 3. Cria a run + items
        lawsuit_ids = sorted(set(cnj_to_id.values()))
        id_to_cnj = {v: k for k, v in cnj_to_id.items()}

        run = VarreduraRun(
            status=RUN_STATUS_RUNNING,
            started_at=datetime.now(timezone.utc),
            responsible_office_ids=[],
            window_days=30,
            triggered_by="prioritaria-master",
            total_processos=len(lawsuit_ids),
        )
        db.add(run)
        db.flush()
        for lid in lawsuit_ids:
            db.add(
                VarreduraProcessado(
                    run_id=run.id,
                    lawsuit_id=lid,
                    cnj_number=id_to_cnj.get(lid),
                    queue_status=QUEUE_STATUS_PENDING,
                )
            )
        db.commit()
        logger.info(
            "Run #%s criada com %s processos (de %s CNJs). "
            "Iniciando subprocess Node SINCRONO inline...",
            run.id, len(lawsuit_ids), len(cnjs_raw),
        )

        # 4. Roda subprocess inline (bloqueia ate terminar)
        _run_subprocess_worker_impl(db, run.id)
        logger.info("Run #%s concluida.", run.id)
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("Falha catastrofica: %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
