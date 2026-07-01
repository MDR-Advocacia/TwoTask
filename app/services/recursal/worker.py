"""
Worker de background da Análise Recursal.

Torna o fluxo fire-and-forget: o operador sobe o PDF e pode fechar a tela.
A cada tick (default 3 min) este job:
  1. AUTO-SUBMETE os processos pendentes (status RECEBIDO) num batch Sonnet;
  2. APLICA os resultados dos batches que a Anthropic já terminou —
     escrevendo os vereditos no banco, INDEPENDENTE de alguém estar na
     tela clicando "Atualizar resultado".

Advisory lock = só um worker do uvicorn roda por vez. As chamadas ao
classifier são assíncronas (httpx), então rodamos via asyncio.run dentro
do tick (que a APScheduler executa numa thread).
"""

import asyncio
import logging

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

JOB_ID = "recursal_auto_worker"
_LOCK_KEY = 826100005  # dedicado (ingest usa ...004, onerequest 001-003)


async def _run(db) -> None:
    from app.models.analise_recursal import (
        RCR_BATCH_STATUS_IN_PROGRESS,
        RCR_BATCH_STATUS_SUBMITTED,
        AnaliseRecursalBatch,
    )
    from app.services.recursal.classifier import RecursalBatchClassifier

    c = RecursalBatchClassifier(db=db)

    # 1. Auto-submete os pendentes (RECEBIDO com íntegra).
    pendentes = c.collect_pending()
    if pendentes:
        try:
            batch = await c.submit_batch(pendentes, requested_by_email="auto-worker")
            logger.info(
                "Recursal auto-worker: submetidos %d processo(s) (batch %s).",
                len(pendentes), batch.id,
            )
        except Exception:
            logger.exception("Recursal auto-worker: falha ao submeter pendentes.")

    # 2. Aplica os batches que ainda não foram aplicados (quando prontos).
    abertos = (
        db.query(AnaliseRecursalBatch)
        .filter(
            AnaliseRecursalBatch.status.in_(
                [RCR_BATCH_STATUS_SUBMITTED, RCR_BATCH_STATUS_IN_PROGRESS]
            )
        )
        .filter(AnaliseRecursalBatch.applied_at.is_(None))
        .all()
    )
    for batch in abertos:
        try:
            await c.refresh_batch_status(batch)
            if batch.results_url and batch.applied_at is None:
                summary = await c.apply_batch_results(batch)
                logger.info(
                    "Recursal auto-worker: batch %s aplicado — %s.", batch.id, summary
                )
        except Exception:
            logger.exception("Recursal auto-worker: falha no batch %s.", batch.id)


def _tick() -> None:
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.services.onerequest._concurrency import single_worker_lock

    if not getattr(settings, "recursal_auto_worker_enabled", True):
        return

    with single_worker_lock(_LOCK_KEY) as got:
        if not got:
            return
        db = SessionLocal()
        try:
            asyncio.run(_run(db))
        except Exception:
            logger.exception("Recursal auto-worker: erro inesperado no tick.")
        finally:
            db.close()


def register_recursal_worker(scheduler) -> None:
    from app.core.config import settings

    if not getattr(settings, "recursal_auto_worker_enabled", True):
        logger.info("Recursal auto-worker: desabilitado por setting — não registrado.")
        return

    interval = int(getattr(settings, "recursal_auto_worker_interval_seconds", 180))
    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(seconds=interval),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Recursal auto-worker: registrado (a cada %ds) — auto-submete e auto-aplica.",
        interval,
    )
