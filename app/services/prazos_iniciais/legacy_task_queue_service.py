from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.prazo_inicial import INTAKE_STATUS_SCHEDULED, PrazoInicialIntake
from app.models.prazo_inicial_legacy_task_queue import (
    QUEUE_STATUS_CANCELLED,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    PrazoInicialLegacyTaskCancellationItem,
)
from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
    LegacyTaskCancellationService,
)
from app.services.prazos_iniciais.legacy_task_circuit_breaker import (
    INFRASTRUCTURE_FAILURE_REASONS,
    get_circuit_breaker,
)

logger = logging.getLogger(__name__)

QUEUE_SUCCESS_REASONS = {
    "cancelled",
    "already_cancelled",
    "already_in_target_status",
}

# Motivo gravado quando o operador cancela manualmente um item da fila pela UI.
MANUAL_CANCEL_REASON = "manually_cancelled"


class PrazosIniciaisLegacyTaskQueueService:
    def __init__(
        self,
        db: Session,
        *,
        cancellation_service: Optional[LegacyTaskCancellationService] = None,
    ):
        self.db = db
        self.cancellation_service = cancellation_service or LegacyTaskCancellationService()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _item_to_dict(self, item: PrazoInicialLegacyTaskCancellationItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "intake_id": item.intake_id,
            "lawsuit_id": item.lawsuit_id,
            "cnj_number": item.cnj_number,
            "office_id": item.office_id,
            "legacy_task_type_external_id": item.legacy_task_type_external_id,
            "legacy_task_subtype_external_id": item.legacy_task_subtype_external_id,
            "queue_status": item.queue_status,
            "attempt_count": item.attempt_count,
            "selected_task_id": item.selected_task_id,
            "cancelled_task_id": item.cancelled_task_id,
            "last_reason": item.last_reason,
            "last_attempt_at": item.last_attempt_at.isoformat() if item.last_attempt_at else None,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "last_error": item.last_error,
            "last_result": item.last_result,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }

    def sync_item_from_intake(
        self,
        intake: PrazoInicialIntake,
        *,
        commit: bool = True,
        legacy_task_type_external_id: int = DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        legacy_task_subtype_external_id: int = DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        force_queue: bool = False,
    ) -> Optional[PrazoInicialLegacyTaskCancellationItem]:
        """
        Garante que um intake AGENDADO tenha um item pendente na fila de
        cancelamento da task legada.

        Se o intake sair de AGENDADO, um item ainda não concluído é cancelado.
        """
        now = self._utcnow()
        item = intake.legacy_task_cancellation_item
        should_queue = (
            (force_queue or intake.status == INTAKE_STATUS_SCHEDULED)
            and (intake.lawsuit_id is not None or bool(intake.cnj_number))
        )

        if not should_queue:
            if item is not None and item.queue_status != QUEUE_STATUS_COMPLETED:
                item.queue_status = QUEUE_STATUS_CANCELLED
                item.updated_at = now
                item.last_reason = "intake_not_eligible"
            if commit:
                self.db.commit()
            return item

        if item is None:
            item = PrazoInicialLegacyTaskCancellationItem(
                intake_id=intake.id,
                lawsuit_id=intake.lawsuit_id,
                cnj_number=intake.cnj_number,
                office_id=intake.office_id,
                legacy_task_type_external_id=legacy_task_type_external_id,
                legacy_task_subtype_external_id=legacy_task_subtype_external_id,
                queue_status=QUEUE_STATUS_PENDING,
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
            self.db.add(item)
            intake.legacy_task_cancellation_item = item
        else:
            previous_status = item.queue_status
            config_changed = (
                item.legacy_task_type_external_id != legacy_task_type_external_id
                or item.legacy_task_subtype_external_id != legacy_task_subtype_external_id
            )
            item.lawsuit_id = intake.lawsuit_id
            item.cnj_number = intake.cnj_number
            item.office_id = intake.office_id
            item.legacy_task_type_external_id = legacy_task_type_external_id
            item.legacy_task_subtype_external_id = legacy_task_subtype_external_id
            if previous_status in {QUEUE_STATUS_CANCELLED, QUEUE_STATUS_FAILED} or config_changed:
                item.queue_status = QUEUE_STATUS_PENDING
                item.completed_at = None
                item.last_error = None
                item.last_result = None
                item.last_reason = None
                item.selected_task_id = None
                item.cancelled_task_id = None
            item.updated_at = now

        if commit:
            self.db.commit()
        return item

    def get_item(self, item_id: int) -> Optional[PrazoInicialLegacyTaskCancellationItem]:
        return (
            self.db.query(PrazoInicialLegacyTaskCancellationItem)
            .options(joinedload(PrazoInicialLegacyTaskCancellationItem.intake))
            .filter(PrazoInicialLegacyTaskCancellationItem.id == item_id)
            .first()
        )

    def list_items(
        self,
        *,
        queue_status: Optional[str] = None,
        limit: int = 100,
        intake_id: Optional[int] = None,
        cnj_number: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        query = (
            self.db.query(PrazoInicialLegacyTaskCancellationItem)
            .order_by(PrazoInicialLegacyTaskCancellationItem.id.desc())
        )
        if queue_status:
            query = query.filter(PrazoInicialLegacyTaskCancellationItem.queue_status == queue_status)
        if intake_id is not None:
            query = query.filter(PrazoInicialLegacyTaskCancellationItem.intake_id == intake_id)
        if cnj_number:
            cleaned = cnj_number.strip()
            if cleaned:
                query = query.filter(
                    PrazoInicialLegacyTaskCancellationItem.cnj_number.ilike(f"%{cleaned}%")
                )
        if since is not None:
            query = query.filter(
                PrazoInicialLegacyTaskCancellationItem.updated_at >= since
            )
        if until is not None:
            query = query.filter(
                PrazoInicialLegacyTaskCancellationItem.updated_at <= until
            )
        return [self._item_to_dict(item) for item in query.limit(limit).all()]

    def process_item(
        self,
        item: PrazoInicialLegacyTaskCancellationItem,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = self._utcnow()
        tick_start = time.monotonic()
        item_id = item.id
        intake_id = item.intake_id
        cnj_number = item.cnj_number
        lawsuit_id = item.lawsuit_id

        item.queue_status = QUEUE_STATUS_PROCESSING
        item.attempt_count = int(item.attempt_count or 0) + 1
        item.last_attempt_at = now
        item.updated_at = now
        if commit:
            self.db.commit()
            self.db.refresh(item)
        else:
            self.db.flush()

        logger.info(
            "legacy_task_queue.process_item.start",
            extra={
                "event": "legacy_task_queue.process_item.start",
                "item_id": item_id,
                "intake_id": intake_id,
                "cnj_number": cnj_number,
                "lawsuit_id": lawsuit_id,
                "attempt_count": item.attempt_count,
            },
        )

        try:
            result = self.cancellation_service.cancel_task(
                cnj_number=item.cnj_number,
                lawsuit_id=item.lawsuit_id,
                task_type_external_id=item.legacy_task_type_external_id,
                task_subtype_external_id=item.legacy_task_subtype_external_id,
                candidate_status_ids=[0, 3],
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - tick_start) * 1000)
            logger.exception(
                "legacy_task_queue.process_item.exception",
                extra={
                    "event": "legacy_task_queue.process_item.exception",
                    "item_id": item_id,
                    "intake_id": intake_id,
                    "cnj_number": cnj_number,
                    "lawsuit_id": lawsuit_id,
                    "attempt_count": item.attempt_count,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
            )
            item.queue_status = QUEUE_STATUS_FAILED
            item.last_reason = "exception"
            item.last_error = str(exc)
            item.updated_at = self._utcnow()
            if commit:
                self.db.commit()
                self.db.refresh(item)
            return {
                "item": self._item_to_dict(item),
                "result": None,
            }

        item.last_result = result
        item.last_reason = result.get("reason")
        item.selected_task_id = result.get("task_id")
        if result.get("reason") in QUEUE_SUCCESS_REASONS:
            item.queue_status = QUEUE_STATUS_COMPLETED
            item.cancelled_task_id = result.get("task_id")
            item.completed_at = self._utcnow()
            item.last_error = None
        else:
            item.queue_status = QUEUE_STATUS_FAILED
            item.last_error = (
                result.get("runner_error")
                or result.get("reason")
                or "Falha ao cancelar task legada."
            )
        item.updated_at = self._utcnow()

        duration_ms = int((time.monotonic() - tick_start) * 1000)
        logger.info(
            "legacy_task_queue.process_item.finish",
            extra={
                "event": "legacy_task_queue.process_item.finish",
                "item_id": item_id,
                "intake_id": intake_id,
                "cnj_number": cnj_number,
                "lawsuit_id": lawsuit_id,
                "attempt_count": item.attempt_count,
                "duration_ms": duration_ms,
                "queue_status": item.queue_status,
                "reason": item.last_reason,
                "task_id": result.get("task_id"),
            },
        )

        if commit:
            self.db.commit()
            self.db.refresh(item)
        return {
            "item": self._item_to_dict(item),
            "result": result,
        }

    def process_pending_items(
        self,
        *,
        limit: int = 20,
        intake_id: Optional[int] = None,
    ) -> dict[str, Any]:
        tick_id = uuid.uuid4().hex[:12]
        tick_start = time.monotonic()
        cb = get_circuit_breaker()
        # Intakes pedidos explicitamente (pós-confirmação de agendamento) ignoram
        # o circuit breaker — é chamada sob demanda, não o worker periódico.
        if intake_id is None and cb.is_tripped():
            snapshot = cb.snapshot()
            logger.warning(
                "legacy_task_queue.tick.skipped_circuit_breaker",
                extra={
                    "event": "legacy_task_queue.tick.skipped_circuit_breaker",
                    "tick_id": tick_id,
                    "tripped_until": (
                        snapshot.tripped_until.isoformat()
                        if snapshot.tripped_until
                        else None
                    ),
                    "last_trip_reason": snapshot.last_trip_reason,
                    "consecutive_failures": snapshot.consecutive_failures,
                },
            )
            return {
                "processed_count": 0,
                "eligible_count": 0,
                "items": [],
                "circuit_breaker_tripped": True,
                "circuit_breaker_tripped_during_tick": False,
                "success_count": 0,
                "failure_count": 0,
                "duration_ms": 0,
                "tick_id": tick_id,
            }

        query = (
            self.db.query(PrazoInicialLegacyTaskCancellationItem)
            .order_by(PrazoInicialLegacyTaskCancellationItem.id.asc())
        )
        if intake_id is not None:
            query = query.filter(PrazoInicialLegacyTaskCancellationItem.intake_id == intake_id)
        else:
            query = query.filter(
                PrazoInicialLegacyTaskCancellationItem.queue_status.in_(
                    [QUEUE_STATUS_PENDING, QUEUE_STATUS_FAILED]
                )
            )

        items = query.limit(limit).all()
        eligible_count = len(items)

        logger.info(
            "legacy_task_queue.tick.start",
            extra={
                "event": "legacy_task_queue.tick.start",
                "tick_id": tick_id,
                "eligible_count": eligible_count,
                "intake_id": intake_id,
                "limit": limit,
            },
        )

        # Guarda porque depois usamos o valor no summary devolvido — o loop
        # pode pular itens que mudaram de status entre o SELECT e o refresh,
        # então processed_count != eligible_count é o caso geral.
        snapshot_eligible_count = eligible_count

        rate_limit_seconds = max(
            0.0,
            float(settings.prazos_iniciais_legacy_task_cancel_rate_limit_seconds or 0.0),
        )

        processed: list[dict[str, Any]] = []
        success_count = 0
        failure_count = 0
        circuit_breaker_tripped_during_tick = False
        for index, item in enumerate(items):
            self.db.refresh(item)
            if item.queue_status not in {QUEUE_STATUS_PENDING, QUEUE_STATUS_FAILED}:
                continue
            if index > 0 and rate_limit_seconds > 0.0:
                time.sleep(rate_limit_seconds)

            outcome = self.process_item(item, commit=True)
            processed.append(outcome)

            reason = outcome["item"].get("last_reason")

            if reason in QUEUE_SUCCESS_REASONS:
                success_count += 1
                cb.record_success()
            else:
                failure_count += 1
                # Apenas falhas de infraestrutura (auth/timeout/exception)
                # alimentam o breaker. Falhas de dado (task_not_found, etc.)
                # não contam — são incrementadas em failure_count mas saem do
                # branch aqui sem tocar no breaker.
                if intake_id is None and reason in INFRASTRUCTURE_FAILURE_REASONS:
                    tripped_now = cb.record_failure(reason)
                    if tripped_now:
                        circuit_breaker_tripped_during_tick = True
                        snapshot = cb.snapshot()
                        logger.warning(
                            "legacy_task_queue.tick.circuit_breaker_tripped",
                            extra={
                                "event": "legacy_task_queue.tick.circuit_breaker_tripped",
                                "tick_id": tick_id,
                                "item_id": item.id,
                                "intake_id": item.intake_id,
                                "tripped_until": (
                                    snapshot.tripped_until.isoformat()
                                    if snapshot.tripped_until
                                    else None
                                ),
                                "consecutive_failures": snapshot.consecutive_failures,
                                "threshold": snapshot.threshold,
                                "reason": reason,
                            },
                        )
                        break  # deixa o próximo tick decidir

        duration_ms = int((time.monotonic() - tick_start) * 1000)
        logger.info(
            "legacy_task_queue.tick.finish",
            extra={
                "event": "legacy_task_queue.tick.finish",
                "tick_id": tick_id,
                "eligible_count": eligible_count,
                "processed_count": len(processed),
                "success_count": success_count,
                "failure_count": failure_count,
                "duration_ms": duration_ms,
                "circuit_breaker_tripped_during_tick": circuit_breaker_tripped_during_tick,
                "intake_id": intake_id,
            },
        )

        return {
            "processed_count": len(processed),
            "eligible_count": snapshot_eligible_count,
            "items": processed,
            "circuit_breaker_tripped": False,
            "circuit_breaker_tripped_during_tick": circuit_breaker_tripped_during_tick,
            "success_count": success_count,
            "failure_count": failure_count,
            "duration_ms": duration_ms,
            "tick_id": tick_id,
        }

    # ── ações do operador (UI) ─────────────────────────────────────────

    def reprocess_item(self, item_id: int) -> Optional[dict[str, Any]]:
        """
        Reset manual: zera status pra PENDENTE e limpa erro pro próximo tick
        agarrar. Não executa o runner aqui — mantém idempotência e mantém a
        execução no worker/endpoint de processamento.
        """
        item = self.get_item(item_id)
        if item is None:
            return None
        now = self._utcnow()
        item.queue_status = QUEUE_STATUS_PENDING
        item.last_error = None
        item.last_reason = None
        item.last_result = None
        item.completed_at = None
        item.updated_at = now
        self.db.commit()
        self.db.refresh(item)
        logger.info(
            "legacy_task_queue.reprocess_item",
            extra={
                "event": "legacy_task_queue.reprocess_item",
                "item_id": item.id,
                "intake_id": item.intake_id,
                "attempt_count": item.attempt_count,
            },
        )
        return self._item_to_dict(item)

    def cancel_item(self, item_id: int) -> Optional[dict[str, Any]]:
        """Cancela manualmente um item (o operador decide abortar o retry)."""
        item = self.get_item(item_id)
        if item is None:
            return None
        now = self._utcnow()
        item.queue_status = QUEUE_STATUS_CANCELLED
        item.last_reason = MANUAL_CANCEL_REASON
        item.updated_at = now
        self.db.commit()
        self.db.refresh(item)
        logger.info(
            "legacy_task_queue.cancel_item",
            extra={
                "event": "legacy_task_queue.cancel_item",
                "item_id": item.id,
                "intake_id": item.intake_id,
            },
        )
        return self._item_to_dict(item)

    # ── métricas para /metrics e exports ───────────────────────────────

    def aggregate_metrics(self, *, hours: int = 24) -> dict[str, Any]:
        """
        Snapshot agregado da fila pro endpoint de observabilidade.

        Inclui:
        - Total por status (PENDENTE/PROCESSANDO/CONCLUIDO/FALHA/CANCELADO).
        - Contagem e latência média (completed_at - last_attempt_at) dos
          concluídos na janela `hours`.
        - Contagem de falhas agrupadas por `last_reason` na janela `hours`.
        - Snapshot do circuit breaker (pra UI mostrar o badge sem precisar
          bater em outro endpoint).
        """
        hours = max(1, int(hours))
        now = self._utcnow()
        window_start = now - timedelta(hours=hours)

        status_rows = (
            self.db.query(
                PrazoInicialLegacyTaskCancellationItem.queue_status,
                func.count(PrazoInicialLegacyTaskCancellationItem.id),
            )
            .group_by(PrazoInicialLegacyTaskCancellationItem.queue_status)
            .all()
        )
        totals_by_status: dict[str, int] = {
            status: int(count or 0) for status, count in status_rows
        }

        # Latência dos concluídos na janela (computada em Python pra não
        # depender de função específica de SQL — SQLite nos testes não tem
        # EXTRACT(EPOCH) etc).
        completed_rows = (
            self.db.query(
                PrazoInicialLegacyTaskCancellationItem.last_attempt_at,
                PrazoInicialLegacyTaskCancellationItem.completed_at,
            )
            .filter(
                PrazoInicialLegacyTaskCancellationItem.queue_status == QUEUE_STATUS_COMPLETED,
                PrazoInicialLegacyTaskCancellationItem.completed_at >= window_start,
            )
            .all()
        )
        latencies_ms: list[int] = []
        for attempt_at, completed_at in completed_rows:
            if attempt_at is None or completed_at is None:
                continue
            delta = completed_at - attempt_at
            ms = int(delta.total_seconds() * 1000)
            if ms < 0:
                continue
            latencies_ms.append(ms)
        completed_in_window = len(completed_rows)
        avg_latency_ms = (
            int(sum(latencies_ms) / len(latencies_ms)) if latencies_ms else None
        )

        failure_reason_rows = (
            self.db.query(
                PrazoInicialLegacyTaskCancellationItem.last_reason,
                func.count(PrazoInicialLegacyTaskCancellationItem.id),
            )
            .filter(
                PrazoInicialLegacyTaskCancellationItem.queue_status == QUEUE_STATUS_FAILED,
                PrazoInicialLegacyTaskCancellationItem.last_attempt_at >= window_start,
            )
            .group_by(PrazoInicialLegacyTaskCancellationItem.last_reason)
            .all()
        )
        failures_by_reason: dict[str, int] = {
            (reason or "unknown"): int(count or 0) for reason, count in failure_reason_rows
        }
        failures_in_window = sum(failures_by_reason.values())

        cb_snapshot = get_circuit_breaker().snapshot()
        circuit_breaker = {
            "tripped": cb_snapshot.tripped,
            "tripped_until": (
                cb_snapshot.tripped_until.isoformat()
                if cb_snapshot.tripped_until
                else None
            ),
            "consecutive_failures": cb_snapshot.consecutive_failures,
            "threshold": cb_snapshot.threshold,
            "cooldown_minutes": cb_snapshot.cooldown_minutes,
            "last_trip_reason": cb_snapshot.last_trip_reason,
            "last_trip_at": (
                cb_snapshot.last_trip_at.isoformat()
                if cb_snapshot.last_trip_at
                else None
            ),
            "last_reset_at": (
                cb_snapshot.last_reset_at.isoformat()
                if cb_snapshot.last_reset_at
                else None
            ),
            "counted_reasons": list(cb_snapshot.counted_reasons),
        }

        return {
            "window_hours": hours,
            "window_start": window_start.isoformat(),
            "now": now.isoformat(),
            "totals_by_status": totals_by_status,
            "completed_in_window": completed_in_window,
            "failures_in_window": failures_in_window,
            "failures_by_reason_in_window": failures_by_reason,
            "avg_latency_ms_in_window": avg_latency_ms,
            "latency_samples_in_window": len(latencies_ms),
            "circuit_breaker": circuit_breaker,
            "rate_limit_seconds": float(
                settings.prazos_iniciais_legacy_task_cancel_rate_limit_seconds or 0.0
            ),
        }
