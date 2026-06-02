"""Apos a run #17 (complementar) terminar, processa IA dos 4170 novos
e gera XLSX FINAL consolidado (run #16 + run #17).

Uso:
    docker exec -d onetask-api-1 python //app/app/runners/legalone/_finalizar_planilha.py
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LOG_PATH = Path(
    "/app/output/playwright/legalone/varredura-andamentos/finalizar.log"
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
logger = logging.getLogger("varredura.finalizar")

CAPA_MAP_PATH = Path("/tmp/varredura-capa-map.json")
RELATORIOS_CACHE = Path("/tmp/varredura-relatorios-cache.json")


def main() -> None:
    # Importa funcoes do script original
    sys.path.insert(0, "/app/app/runners/legalone")
    from _run_planilha_relatorios import (
        chamar_sonnet,
        gerar_xlsx_final,
    )

    from app.db.session import SessionLocal
    from app.models.varredura import VarreduraRun

    # 1. Aguarda run #17 terminar (status != RUNNING)
    logger.info("Aguardando run #17 terminar...")
    while True:
        db = SessionLocal()
        try:
            run17 = db.query(VarreduraRun).filter(VarreduraRun.id == 17).first()
            if run17 is None:
                logger.error("Run #17 nao existe ainda. Abortando.")
                return
            if run17.status != "RUNNING":
                logger.info("Run #17 terminou. Status: %s", run17.status)
                break
        finally:
            db.close()
        time.sleep(60)

    # 2. Le status.json das DUAS runs (#16 + #17) — reprocessa tudo
    # com novo prompt (mais restritivo, so' prazos do REU + sem mencao IA).
    status16 = Path(
        "/app/output/playwright/legalone/varredura-andamentos/run-16/status.json"
    )
    status17 = Path(
        "/app/output/playwright/legalone/varredura-andamentos/run-17/status.json"
    )
    items_all: list = []
    for sp in (status16, status17):
        if sp.exists():
            data = json.loads(sp.read_text(encoding="utf-8"))
            items_all.extend(data.get("items") or [])
            logger.info(
                "Carregado %s: %s items",
                sp.parent.name,
                len(data.get("items") or []),
            )

    capa_by_lawsuit = json.loads(CAPA_MAP_PATH.read_text(encoding="utf-8"))

    # Apaga cache pra forcar reprocessamento com novo prompt
    if RELATORIOS_CACHE.exists():
        RELATORIOS_CACHE.unlink()
        logger.info("Cache de relatorios APAGADO (reprocessamento com novo prompt).")
    cache: dict[int, dict] = {}

    # 3. Processa via Haiku TODOS os items "ok" das duas runs
    todo = []
    seen_lids: set[int] = set()
    for it in items_all:
        if (it.get("status") or "").lower() != "ok":
            continue
        lid = int(it.get("lawsuitId") or 0)
        if not lid or lid in seen_lids:
            continue
        seen_lids.add(lid)
        ands = it.get("andamentos") or []
        capa = capa_by_lawsuit.get(str(lid)) or {}
        todo.append(
            {
                "lawsuit_id": lid,
                "cnj": it.get("cnjNumber") or capa.get("__cnj_original"),
                "andamentos": ands,
                "capa": capa,
            }
        )
    logger.info(
        "Reprocessando TUDO (run #16 + #17): %s processos pra IA Haiku",
        len(todo),
    )

    lock = threading.Lock()
    counter = {"done": 0, "fail": 0}

    def _work(p):
        lid = p["lawsuit_id"]
        try:
            r = chamar_sonnet(p)
            with lock:
                cache[lid] = r
                counter["done"] += 1
                if counter["done"] % 100 == 0:
                    RELATORIOS_CACHE.write_text(
                        json.dumps(
                            {str(k): v for k, v in cache.items()},
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    logger.info(
                        "IA Haiku (reprocesso): %s/%s (falhas: %s)",
                        counter["done"], len(todo), counter["fail"],
                    )
        except Exception as exc:
            with lock:
                counter["fail"] += 1
                cache[lid] = {"error": str(exc)[:300]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_work, p) for p in todo]
        for _ in as_completed(futures):
            pass

    RELATORIOS_CACHE.write_text(
        json.dumps(
            {str(k): v for k, v in cache.items()}, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info(
        "IA Haiku #17 concluida. Total cache: %s, sucesso: %s, falhas: %s",
        len(cache), counter["done"], counter["fail"],
    )

    # 4. Gera XLSX FINAL consolidado (usa todos os relatorios em cache)
    db = SessionLocal()
    try:
        # Repassa run #17 pra função (mas a XLSX usa capa_map + cache que ja
        # tem tudo). Vou regenerar usando capa_by_lawsuit (5957 processos)
        # e cache (>= 1787 + 4170).
        out = gerar_xlsx_final(17, capa_by_lawsuit, cache)
        logger.info("XLSX FINAL gerada: %s (%s bytes)", out, out.stat().st_size)
    finally:
        db.close()


if __name__ == "__main__":
    main()
