"""Aguarda o _loop_completar_pendentes.py terminar (procura por
'LOOP ENCERRADO' no log) e gera XLSX FINAL FINAL agregando items
'ok' de TODAS as runs da feature planilha-relatorios.

Reusa cache de relatorios existente (so' chama Haiku pros novos).

Uso:
    docker exec -d onetask-api-1 python //app/app/runners/legalone/_finalizar_pos_loop.py
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
    "/app/output/playwright/legalone/varredura-andamentos/finalizar-pos-loop.log"
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
logger = logging.getLogger("varredura.posloop")

LOOP_LOG = Path(
    "/app/output/playwright/legalone/varredura-andamentos/loop-completar.log"
)
CAPA_MAP_PATH = Path("/tmp/varredura-capa-map.json")
RELATORIOS_CACHE = Path("/tmp/varredura-relatorios-cache.json")
PLANILHA_RUN_IDS_START = 16


def aguardar_loop_terminar() -> None:
    logger.info("Aguardando '_loop_completar_pendentes.py' terminar...")
    while True:
        if LOOP_LOG.exists():
            txt = LOOP_LOG.read_text(encoding="utf-8", errors="ignore")
            if "=== LOOP ENCERRADO ===" in txt:
                logger.info("Loop encerrado. Prosseguindo com finalizacao.")
                return
        time.sleep(120)


def carregar_items_todas_runs() -> list[dict]:
    """Items 'ok' de status.json de todas as runs da feature."""
    from app.db.session import SessionLocal
    from app.models.varredura import VarreduraRun

    base = Path("/app/output/playwright/legalone/varredura-andamentos")
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

    seen: set[int] = set()
    items_out: list[dict] = []
    for r in runs:
        sp = base / f"run-{r.id}" / "status.json"
        if not sp.exists():
            continue
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in data.get("items") or []:
            if (it.get("status") or "").lower() != "ok":
                continue
            lid = int(it.get("lawsuitId") or 0)
            if not lid or lid in seen:
                continue
            seen.add(lid)
            items_out.append(it)
    logger.info("Items 'ok' agregados de %s runs: %s", len(runs), len(items_out))
    return items_out


def main() -> None:
    aguardar_loop_terminar()

    sys.path.insert(0, "/app/app/runners/legalone")
    from _run_planilha_relatorios import chamar_sonnet, gerar_xlsx_final

    items_all = carregar_items_todas_runs()
    capa_by_lawsuit = json.loads(CAPA_MAP_PATH.read_text(encoding="utf-8"))

    # Cache existente (com relatorios da fase anterior — 3571)
    cache: dict[int, dict] = {}
    if RELATORIOS_CACHE.exists():
        raw = json.loads(RELATORIOS_CACHE.read_text(encoding="utf-8"))
        cache = {int(k): v for k, v in raw.items()}
    logger.info("Cache pre-existente: %s entries", len(cache))

    # Determina o que falta processar (items novos nao no cache)
    todo = []
    for it in items_all:
        lid = int(it.get("lawsuitId") or 0)
        if lid in cache and "error" not in cache[lid]:
            continue
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
    logger.info("Items pendentes de IA: %s", len(todo))

    if todo:
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
                            "IA Haiku (final): %s/%s (falhas: %s)",
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
            "IA final concluida: sucesso=%s, falhas=%s",
            counter["done"], counter["fail"],
        )

    out = gerar_xlsx_final(0, capa_by_lawsuit, cache)
    logger.info("XLSX FINAL FINAL gerada: %s (%s bytes)", out, out.stat().st_size)


if __name__ == "__main__":
    main()
