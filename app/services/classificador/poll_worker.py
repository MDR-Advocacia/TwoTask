"""Worker periodico do Classificador — polling de batches Anthropic.

Espelha o pattern do PI (publication_batch_classifier_worker). Roda a
cada 30s, varre batches em ENVIADO/EM_PROCESSAMENTO/PRONTO e:
- Se Anthropic terminou (status=ended): baixa results, materializa
- Se ainda em progresso: atualiza contadores

Registrado no startup do main.py via `register_classificador_poll_job`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.session import SessionLocal
from app.models.classificador import (
    BATCH_STATUS_IN_PROGRESS,
    BATCH_STATUS_READY,
    BATCH_STATUS_SUBMITTED,
    ClassificadorBatch,
)
from app.services.classificador.classifier_runner import (
    ClassificadorBatchClassifier,
)

logger = logging.getLogger(__name__)


POLL_INTERVAL_SECONDS = 30


def _tick() -> None:
    """Roda 1 iteracao do worker — sincrono (APScheduler rodando em thread)."""
    db = SessionLocal()
    try:
        # 1. Refresh status dos batches em curso
        in_progress = (
            db.query(ClassificadorBatch)
            .filter(ClassificadorBatch.status.in_({
                BATCH_STATUS_SUBMITTED, BATCH_STATUS_IN_PROGRESS,
            }))
            .filter(ClassificadorBatch.anthropic_batch_id.isnot(None))
            .all()
        )

        runner = ClassificadorBatchClassifier(db)

        for batch in in_progress:
            try:
                asyncio.run(runner.refresh_batch_status(batch))
                logger.debug(
                    "classificador.poll: batch=%s anthropic_status=%s local=%s",
                    batch.id, batch.anthropic_status, batch.status,
                )
            except Exception as exc:
                logger.warning(
                    "classificador.poll: refresh batch=%s falhou: %s", batch.id, exc,
                )

        # 2. Apply batches que ficaram PRONTO
        ready = (
            db.query(ClassificadorBatch)
            .filter(ClassificadorBatch.status == BATCH_STATUS_READY)
            .filter(ClassificadorBatch.results_url.isnot(None))
            .all()
        )

        for batch in ready:
            try:
                result = asyncio.run(runner.apply_batch_results(batch))
                logger.info(
                    "classificador.poll: applied batch=%s succeeded=%d failed=%d skipped=%d",
                    batch.id, result["succeeded"], result["failed"], result["skipped"],
                )
            except Exception as exc:
                logger.exception(
                    "classificador.poll: apply batch=%s falhou: %s", batch.id, exc,
                )
    finally:
        db.close()


def register_classificador_poll_job(scheduler: BackgroundScheduler) -> None:
    """Registra o tick periodico no scheduler global."""
    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(seconds=POLL_INTERVAL_SECONDS),
        id="classificador_poll_batches",
        name="Classificador — polling de batches Anthropic",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # primeira rodada imediata
    )
    logger.info(
        "classificador_poll_worker: registrado (interval=%ds)",
        POLL_INTERVAL_SECONDS,
    )
