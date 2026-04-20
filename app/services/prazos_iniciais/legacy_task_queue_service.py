from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

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

logger = logging.getLogger(__name__)

QUEUE_SUCCESS_REASONS = {
    "cancelled",
    "already_cancelled",
    "already_in_target_status",
}


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
    ) -> Optional[PrazoInicialLegacyTaskCancellationItem]:
        """
        Garante que um intake AGENDADO tenha um item pendente na fila de
        cancelamento da task legada.

        Se o intake sair de AGENDADO, um item ainda não concluído é cancelado.
        """
        now = self._utcnow()
        item = intake.legacy_task_cancellation_item
        should_queue = (
            intake.status == INTAKE_STATUS_SCHEDULED
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
    ) -> list[dict[str, Any]]:
        query = (
            self.db.query(PrazoInicialLegacyTaskCancellationItem)
            .order_by(PrazoInicialLegacyTaskCancellationItem.id.desc())
        )
        if queue_status:
            query = query.filter(PrazoInicialLegacyTaskCancellationItem.queue_status == queue_status)
        return [self._item_to_dict(item) for item in query.limit(limit).all()]

    def process_item(
        self,
        item: PrazoInicialLegacyTaskCancellationItem,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = self._utcnow()
        item.queue_status = QUEUE_STATUS_PROCESSING
        item.attempt_count = int(item.attempt_count or 0) + 1
        item.last_attempt_at = now
        item.updated_at = now
        if commit:
            self.db.commit()
            self.db.refresh(item)
        else:
            self.db.flush()

        try:
            result = self.cancellation_service.cancel_task(
                cnj_number=item.cnj_number,
                lawsuit_id=item.lawsuit_id,
                task_type_external_id=item.legacy_task_type_external_id,
                task_subtype_external_id=item.legacy_task_subtype_external_id,
                candidate_status_ids=[0, 3],
            )
        except Exception as exc:
            logger.exception(
                "Falha ao processar item %s da fila de cancelamento legado.",
                item.id,
            )
            item.queue_status = QUEUE_STATUS_FAILED
            item.last_reason = "exception"
            item.last_error = str(exc)
            item.updated_at = now
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
        processed: list[dict[str, Any]] = []
        for item in items:
            self.db.refresh(item)
            if item.queue_status not in {QUEUE_STATUS_PENDING, QUEUE_STATUS_FAILED}:
                continue
            processed.append(self.process_item(item, commit=True))

        return {
            "processed_count": len(processed),
            "items": processed,
        }
