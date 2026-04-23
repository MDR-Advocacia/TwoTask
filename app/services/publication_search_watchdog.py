"""
Watchdog para buscas de publicações órfãs.

Motivação:
    `create_and_run_search` tem try/except que marca status=FALHA em caso de
    exceção Python. Isso cobre erro "limpo" (timeout do client Legal One,
    erro de ORM, exception de negócio). NÃO cobre SIGKILL/OOM/restart do
    container: quando o kernel mata o worker uvicorn, o `except` nunca
    executa e a `PublicationSearch` fica eternamente com status='EXECUTANDO'.

    A UI faz polling desse registro e mostra a barra de progresso congelada —
    foi exatamente o caso da Busca #2 em 22/04/2026 21:24 (órfã por ~30 min
    até intervenção manual).

Duas atuações:
    1. `reap_orphaned_searches_on_startup()` — chamada no lifespan do FastAPI,
       marca como FALHA qualquer busca deixada em EXECUTANDO no crash anterior.
    2. `register_publication_search_watchdog_job()` — registra um job periódico
       no APScheduler (a cada 5 min) que faz a mesma varredura em runtime, pra
       pegar casos onde um worker específico morre sem o container reiniciar.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.base import BaseScheduler

from app.db.session import SessionLocal
from app.models.publication_search import (
    PublicationSearch,
    SEARCH_STATUS_FAILED,
    SEARCH_STATUS_RUNNING,
)

logger = logging.getLogger(__name__)

# Uma busca sem progresso há mais de ORPHAN_TIMEOUT_MINUTES é considerada morta.
# Escolhido conservador: uma busca real de Diário Oficial (até 5k publicações
# + lookup de lawsuits + classificação opcional) deve caber nesse intervalo.
ORPHAN_TIMEOUT_MINUTES = 30

# Intervalo do job periódico — 5 min é suficiente pra UI não ficar travada
# muito tempo sem um restart de container.
WATCHDOG_INTERVAL_MINUTES = 5


def _reap_orphans(reason: str) -> int:
    """
    Marca como FALHA toda PublicationSearch presa em EXECUTANDO há mais de
    ORPHAN_TIMEOUT_MINUTES. Retorna o número de registros reapados.

    Abre sua própria Session — seguro de chamar do startup ou de um job
    APScheduler (threads separadas da request loop do FastAPI).
    """
    threshold = datetime.now(timezone.utc) - timedelta(minutes=ORPHAN_TIMEOUT_MINUTES)

    db = SessionLocal()
    try:
        orphans = (
            db.query(PublicationSearch)
            .filter(PublicationSearch.status == SEARCH_STATUS_RUNNING)
            .filter(PublicationSearch.created_at < threshold)
            .all()
        )
        if not orphans:
            return 0

        for search in orphans:
            search.status = SEARCH_STATUS_FAILED
            search.error_message = (
                f"Busca órfã detectada ({reason}). "
                f"Worker uvicorn provavelmente morreu durante execução "
                f"(OOM/restart/SIGKILL) — o except do serviço não disparou."
            )[:500]
            search.finished_at = datetime.now(timezone.utc)
            search.progress_step = "ORPHANED"
            search.progress_detail = "Execução interrompida — marcada como falha pelo watchdog."

        db.commit()
        logger.warning(
            "Watchdog de publicações reapou %d busca(s) órfã(s): ids=%s",
            len(orphans), [s.id for s in orphans],
        )
        return len(orphans)
    except Exception:
        db.rollback()
        logger.exception("Falha ao reapear buscas de publicações órfãs.")
        return 0
    finally:
        db.close()


def reap_orphaned_searches_on_startup() -> int:
    """Reap inicial — chamado pelo lifespan do FastAPI em cada startup."""
    return _reap_orphans(reason="startup")


def _watchdog_tick() -> None:
    """Callback do APScheduler — roda a cada WATCHDOG_INTERVAL_MINUTES."""
    _reap_orphans(reason="tick periódico")


def register_publication_search_watchdog_job(scheduler: BaseScheduler) -> None:
    """
    Registra o job periódico no APScheduler singleton.

    Idempotente: se já existe um job com o mesmo id (ex.: re-registro depois
    de um reload), substitui (`replace_existing=True`).

    Observação: com --workers N do uvicorn, cada worker tem seu próprio
    scheduler in-process → o job roda N vezes por tick. Como o reap é
    idempotente (update com filtro por status), isso é inofensivo — só
    gera N vezes o SELECT vazio. Para reduzir, migrar o scheduler pra um
    serviço dedicado quando valer a pena.
    """
    scheduler.add_job(
        _watchdog_tick,
        trigger="interval",
        minutes=WATCHDOG_INTERVAL_MINUTES,
        id="publication_search_watchdog",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Watchdog de publicações registrado no APScheduler (intervalo=%dmin, timeout=%dmin).",
        WATCHDOG_INTERVAL_MINUTES, ORPHAN_TIMEOUT_MINUTES,
    )
