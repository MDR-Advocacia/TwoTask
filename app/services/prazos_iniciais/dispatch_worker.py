"""
Worker periódico do disparo do Tratamento Web (Onda 3 #6).

Roda em intervalo configurável (APScheduler) e dispara em lote os
intakes com `dispatch_pending=True` em ordem cronológica de
`treated_at` ascendente. Cada disparo executa:

  1. Upload da habilitação no GED do processo no Legal One
  2. Enqueue do cancelamento da task legada "Agendar Prazos"

Idempotente: o método `dispatch_treatment_web` do
`PrazosIniciaisSchedulingService` pula GED quando `ged_document_id`
já existe e não duplica itens na fila de cancelamento.

Gatilho: `settings.prazos_iniciais_dispatch_enabled` (default False).
Intervalo: `settings.prazos_iniciais_dispatch_interval_seconds`.
Batch limit: `settings.prazos_iniciais_dispatch_batch_limit`.

Registrado no startup do FastAPI (main.py lifespan).
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.prazo_inicial import PrazoInicialIntake
from app.services.prazos_iniciais.scheduling_service import (
    PrazosIniciaisSchedulingService,
)

logger = logging.getLogger(__name__)


JOB_ID = "prazos_iniciais_dispatch_treatment_web"


def _tick() -> None:
    """Uma execução do worker. Não levanta — apenas loga falhas."""
    db = SessionLocal()
    try:
        batch_limit = max(1, settings.prazos_iniciais_dispatch_batch_limit)

        pending_ids = (
            db.query(PrazoInicialIntake.id)
            .filter(PrazoInicialIntake.dispatch_pending.is_(True))
            .order_by(PrazoInicialIntake.treated_at.asc().nullslast())
            .limit(batch_limit)
            .all()
        )
        intake_ids = [row[0] for row in pending_ids]

        if not intake_ids:
            logger.debug("dispatch_worker: sem intakes pendentes — nada a fazer.")
            return

        service = PrazosIniciaisSchedulingService(db)
        success = 0
        skipped = 0
        failed = 0

        for iid in intake_ids:
            try:
                result = service.dispatch_treatment_web(intake_id=iid)
                if result.get("skipped"):
                    skipped += 1
                else:
                    success += 1
            except Exception:  # noqa: BLE001
                failed += 1
                logger.exception(
                    "dispatch_worker: falha no intake %s (continuando lote).", iid,
                )
                # Loop continua — falhas individuais não interrompem o tick.
                # `dispatch_pending` permanece True pra próximo tick (retry
                # natural) e `dispatch_error_message` é gravado no service.
                continue

        logger.info(
            "dispatch_worker: processado lote (candidates=%d, success=%d, "
            "skipped=%d, failed=%d).",
            len(intake_ids), success, skipped, failed,
        )
    finally:
        db.close()


def _run_tick() -> None:
    """Adapter síncrono pro APScheduler — roda dentro de thread do scheduler."""
    try:
        _tick()
    except Exception:  # noqa: BLE001
        logger.exception("dispatch_worker: erro inesperado no tick.")


def register_dispatch_job(scheduler) -> None:
    """
    Registra o job periódico no scheduler.

    Idempotente — se o job já existir, é substituído (replace_existing=True).
    Não faz nada se a flag global estiver desligada.
    """
    if not settings.prazos_iniciais_dispatch_enabled:
        logger.info(
            "dispatch_worker NÃO registrado "
            "(prazos_iniciais_dispatch_enabled=False). Operador pode disparar "
            "manualmente pela UI.",
        )
        return

    interval = max(60, settings.prazos_iniciais_dispatch_interval_seconds)
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
        "dispatch_worker registrado (intervalo=%ds, batch_limit=%d).",
        interval, settings.prazos_iniciais_dispatch_batch_limit,
    )
