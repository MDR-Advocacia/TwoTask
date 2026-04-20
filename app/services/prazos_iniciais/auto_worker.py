"""
Worker periódico do fluxo "Agendar Prazos Iniciais".

Roda em intervalo configurável (APScheduler) e faz duas coisas:

1. Para cada batch em SUBMITTED/IN_PROGRESS, consulta status e — se já
   terminou na Anthropic — baixa resultados e materializa sugestões.
2. Se houver intakes em PRONTO_PARA_CLASSIFICAR acima do mínimo
   configurado (`prazos_iniciais_batch_min_size`), submete um novo
   batch.

Gatilho: ligado por `settings.prazos_iniciais_auto_classification_enabled`
(default False — para evitar gasto involuntário com Anthropic em dev).
Registrado no startup do FastAPI (main.py lifespan).
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.prazo_inicial import (
    PIN_BATCH_STATUS_IN_PROGRESS,
    PIN_BATCH_STATUS_READY,
    PIN_BATCH_STATUS_SUBMITTED,
    PrazoInicialBatch,
)
from app.services.classifier.prazos_iniciais_classifier import (
    PrazosIniciaisBatchClassifier,
)

logger = logging.getLogger(__name__)


JOB_ID = "prazos_iniciais_auto_classification"


async def _tick_async() -> None:
    """Uma execução do worker. Não levanta — apenas loga falhas."""
    db = SessionLocal()
    try:
        classifier = PrazosIniciaisBatchClassifier(db=db)

        # 1. Pollar batches em andamento.
        pending_batches = (
            db.query(PrazoInicialBatch)
            .filter(
                PrazoInicialBatch.status.in_(
                    [
                        PIN_BATCH_STATUS_SUBMITTED,
                        PIN_BATCH_STATUS_IN_PROGRESS,
                        PIN_BATCH_STATUS_READY,
                    ]
                )
            )
            .all()
        )
        for batch in pending_batches:
            try:
                batch = await classifier.refresh_batch_status(batch)
                if batch.status == PIN_BATCH_STATUS_READY and batch.results_url:
                    summary = await classifier.apply_batch_results(batch)
                    logger.info(
                        "Auto-apply batch %s: %s",
                        batch.anthropic_batch_id, summary,
                    )
            except Exception:
                logger.exception(
                    "Worker: falha ao processar batch %s.", batch.id
                )

        # 2. Enviar novo batch se atingir o tamanho mínimo.
        intakes = classifier.collect_pending_intakes(
            limit=settings.prazos_iniciais_batch_max_size
        )
        min_size = settings.prazos_iniciais_batch_min_size
        if len(intakes) >= max(1, min_size):
            try:
                batch = await classifier.submit_batch(
                    intakes=intakes,
                    requested_by_email="auto-worker",
                )
                logger.info(
                    "Worker: batch enviado (id=%s, intakes=%d).",
                    batch.anthropic_batch_id, len(intakes),
                )
            except Exception:
                logger.exception(
                    "Worker: falha ao submeter batch com %d intake(s).",
                    len(intakes),
                )
        elif intakes:
            logger.debug(
                "Worker: %d intake(s) prontos, abaixo do mínimo (%d) — aguardando.",
                len(intakes), min_size,
            )
    finally:
        db.close()


def _run_tick() -> None:
    """
    Adapter síncrono pro APScheduler — abre/fecha o loop por execução.
    APScheduler `BackgroundScheduler` roda em threads, então cada tick
    precisa do seu próprio event loop.
    """
    try:
        asyncio.run(_tick_async())
    except Exception:
        logger.exception("Erro inesperado no worker de prazos iniciais.")


def register_auto_classification_job(scheduler) -> None:
    """
    Registra o job periódico no scheduler.

    Idempotente — se o job já existir, é substituído (replace_existing=True).
    Não faz nada se a flag global estiver desligada.
    """
    if not settings.prazos_iniciais_auto_classification_enabled:
        logger.info(
            "Worker de prazos iniciais NÃO registrado "
            "(prazos_iniciais_auto_classification_enabled=False)."
        )
        return

    interval = max(60, settings.prazos_iniciais_auto_classification_interval_seconds)
    scheduler.add_job(
        _run_tick,
        trigger="interval",
        seconds=interval,
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Worker de prazos iniciais registrado (intervalo=%ds).", interval
    )
