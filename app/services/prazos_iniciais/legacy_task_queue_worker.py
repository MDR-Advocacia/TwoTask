from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.prazos_iniciais.legacy_task_queue_service import (
    PrazosIniciaisLegacyTaskQueueService,
)

logger = logging.getLogger(__name__)


JOB_ID = "prazos_iniciais_legacy_task_cancellation"


# ── last-tick tracker (in-process) ─────────────────────────────────────
# Guardamos um snapshot do último tick do worker periódico pra ser
# consumido pelo endpoint /metrics sem depender do DB. Estado em memória
# local do processo — mesma justificativa do circuit breaker: APScheduler
# roda 1 instância do job por processo, e isso basta pra UI de operação.


@dataclass
class LastTickState:
    tick_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    eligible_count: int = 0
    processed_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    circuit_breaker_tripped: bool = False
    circuit_breaker_tripped_during_tick: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick_id": self.tick_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "eligible_count": self.eligible_count,
            "processed_count": self.processed_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "circuit_breaker_tripped": self.circuit_breaker_tripped,
            "circuit_breaker_tripped_during_tick": self.circuit_breaker_tripped_during_tick,
            "error": self.error,
        }


@dataclass
class _LastTickHolder:
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: LastTickState = field(default_factory=LastTickState)


_last_tick_holder = _LastTickHolder()


def get_last_tick_state() -> dict[str, Any]:
    with _last_tick_holder.lock:
        return _last_tick_holder.state.to_dict()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _run_tick() -> None:
    start_wall = _utcnow()
    tick_start = time.monotonic()
    db = SessionLocal()
    state = LastTickState(started_at=start_wall)
    try:
        service = PrazosIniciaisLegacyTaskQueueService(db)
        summary = service.process_pending_items(
            limit=max(1, settings.prazos_iniciais_legacy_task_cancellation_batch_size)
        )
        state.tick_id = summary.get("tick_id")
        state.eligible_count = summary.get("processed_count", 0) + (
            # `processed_count` pode ser menor que `eligible_count` se o
            # circuit breaker tripar no meio do tick — service não devolve
            # eligible_count cru, então usamos processed como proxy.
            0
        )
        state.processed_count = int(summary.get("processed_count", 0) or 0)
        state.success_count = int(summary.get("success_count", 0) or 0)
        state.failure_count = int(summary.get("failure_count", 0) or 0)
        state.circuit_breaker_tripped = bool(summary.get("circuit_breaker_tripped"))
        state.circuit_breaker_tripped_during_tick = bool(
            summary.get("circuit_breaker_tripped_during_tick")
        )

        if state.circuit_breaker_tripped:
            logger.info(
                "legacy_task_queue.worker.tick_skipped_circuit_breaker",
                extra={
                    "event": "legacy_task_queue.worker.tick_skipped_circuit_breaker",
                    "tick_id": state.tick_id,
                },
            )
        elif state.processed_count:
            logger.info(
                "legacy_task_queue.worker.tick_processed",
                extra={
                    "event": "legacy_task_queue.worker.tick_processed",
                    "tick_id": state.tick_id,
                    "processed_count": state.processed_count,
                    "success_count": state.success_count,
                    "failure_count": state.failure_count,
                    "circuit_breaker_tripped_during_tick": state.circuit_breaker_tripped_during_tick,
                },
            )
    except Exception as exc:
        state.error = str(exc)
        logger.exception(
            "legacy_task_queue.worker.tick_exception",
            extra={
                "event": "legacy_task_queue.worker.tick_exception",
                "error": str(exc),
            },
        )
    finally:
        db.close()
        state.finished_at = _utcnow()
        state.duration_ms = int((time.monotonic() - tick_start) * 1000)
        with _last_tick_holder.lock:
            _last_tick_holder.state = state


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
