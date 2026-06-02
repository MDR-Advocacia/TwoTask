"""Reprocessa os 1787 OK da run #16 com novo prompt (so' prazos do REU
+ sem mencao IA no relatorio), gera XLSX parcial atualizada.

Uso:
    docker exec -d onetask-api-1 python //app/app/runners/legalone/_reprocessar_run16.py
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LOG_PATH = Path(
    "/app/output/playwright/legalone/varredura-andamentos/reprocessar-run16.log"
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
logger = logging.getLogger("varredura.reprocessar16")

CAPA_MAP_PATH = Path("/tmp/varredura-capa-map.json")
RELATORIOS_CACHE = Path("/tmp/varredura-relatorios-cache.json")


def main() -> None:
    sys.path.insert(0, "/app/app/runners/legalone")
    from _run_planilha_relatorios import chamar_sonnet, gerar_xlsx_final

    status16 = Path(
        "/app/output/playwright/legalone/varredura-andamentos/run-16/status.json"
    )
    data = json.loads(status16.read_text(encoding="utf-8"))
    items = data.get("items") or []
    capa_by_lawsuit = json.loads(CAPA_MAP_PATH.read_text(encoding="utf-8"))

    # Apaga cache pra reprocessar com novo prompt
    if RELATORIOS_CACHE.exists():
        RELATORIOS_CACHE.unlink()
        logger.info("Cache APAGADO. Reprocessando com novo prompt...")
    cache: dict[int, dict] = {}

    todo = []
    seen: set[int] = set()
    for it in items:
        if (it.get("status") or "").lower() != "ok":
            continue
        lid = int(it.get("lawsuitId") or 0)
        if not lid or lid in seen:
            continue
        seen.add(lid)
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
    logger.info("Run #16: reprocessando %s processos com IA Haiku", len(todo))

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
                        json.dumps({str(k): v for k, v in cache.items()}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    logger.info(
                        "Reproc IA: %s/%s (falhas: %s)",
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
        json.dumps({str(k): v for k, v in cache.items()}, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "Reproc IA concluida: %s sucesso / %s falhas",
        counter["done"], counter["fail"],
    )

    # Gera XLSX parcial atualizada
    out = gerar_xlsx_final(16, capa_by_lawsuit, cache)
    logger.info("XLSX PARCIAL atualizada: %s (%s bytes)", out, out.stat().st_size)


if __name__ == "__main__":
    main()
