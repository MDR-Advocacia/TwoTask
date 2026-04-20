from __future__ import annotations

import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.prazos_iniciais.legacy_task_queue_service import (
    PrazosIniciaisLegacyTaskQueueService,
)

logger = logging.getLogger(__name__)


JOB_ID = "prazos_iniciais_legacy_task_cancellation"


def _run_tick() -> None:
    db = SessionLocal()
    try:
        service = PrazosIniciaisLegacyTaskQueueService(db)
        summary = service.process_pending_items(
            limit=max(1, settings.prazos_iniciais_legacy_task_cancellation_batch_size)
        )
        if summary["processed_count"]:
            logger.info(
                "Worker de cancelamento legado processou %d item(ns).",
                summary["processed_count"],
            )
    except Exception:
        logger.exception("Erro inesperado no worker de cancelamento legado.")
    finally:
        db.close()


def register_legacy_task_cancellation_job(scheduler) -> None:
    if not settings.prazos_iniciais_legacy_task_cancellation_enabled:
        logger.info(
            "Worker de cancelamento legado de prazos iniciais não registrado "
            "(prazos_iniciais_legacy_task_cancellation_enabled=False)."
        )
        return

    interval = max(15, settings.prazos_iniciais_legacy_task_cancellation_interval_seconds)
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
        "Worker de cancelamento legado de prazos iniciais registrado (intervalo=%ds).",
        interval,
    )
