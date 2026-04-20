from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models.prazo_inicial import (
    INTAKE_STATUS_CLASSIFIED,
    INTAKE_STATUS_IN_REVIEW,
    INTAKE_STATUS_SCHEDULE_ERROR,
    INTAKE_STATUS_SCHEDULED,
    SUGESTAO_REVIEW_APPROVED,
    SUGESTAO_REVIEW_EDITED,
    SUGESTAO_REVIEW_PENDING,
    SUGESTAO_REVIEW_REJECTED,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
)
from app.services.prazos_iniciais.legacy_task_queue_service import (
    PrazosIniciaisLegacyTaskQueueService,
)


VALID_CONFIRM_REVIEW_STATUSES = {
    SUGESTAO_REVIEW_APPROVED,
    SUGESTAO_REVIEW_EDITED,
}


@dataclass(frozen=True)
class ConfirmedSuggestionInput:
    suggestion_id: int
    created_task_id: Optional[int] = None
    review_status: Optional[str] = None


class PrazosIniciaisSchedulingService:
    def __init__(self, db: Session):
        self.db = db
        self.queue_service = PrazosIniciaisLegacyTaskQueueService(db)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _load_intake(self, intake_id: int) -> Optional[PrazoInicialIntake]:
        return (
            self.db.query(PrazoInicialIntake)
            .options(joinedload(PrazoInicialIntake.sugestoes))
            .filter(PrazoInicialIntake.id == intake_id)
            .first()
        )

    def confirm_intake_scheduling(
        self,
        *,
        intake_id: int,
        confirmed_suggestions: Optional[list[ConfirmedSuggestionInput]],
        confirmed_by_email: str,
        enqueue_legacy_task_cancellation: bool = True,
        legacy_task_type_external_id: int = DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        legacy_task_subtype_external_id: int = DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    ) -> dict:
        intake = self._load_intake(intake_id)
        if intake is None:
            raise ValueError("Intake não encontrado.")

        allowed_statuses = {
            INTAKE_STATUS_IN_REVIEW,
            INTAKE_STATUS_CLASSIFIED,
            INTAKE_STATUS_SCHEDULED,
            INTAKE_STATUS_SCHEDULE_ERROR,
        }
        if intake.status not in allowed_statuses:
            raise RuntimeError(
                f"Confirmação permitida apenas em EM_REVISAO / CLASSIFICADO / AGENDADO / ERRO_AGENDAMENTO. Status atual: {intake.status}."
            )

        by_id = {s.id: s for s in intake.sugestoes or []}
        now = self._utcnow()

        if confirmed_suggestions:
            selected: list[tuple[PrazoInicialSugestao, ConfirmedSuggestionInput]] = []
            for entry in confirmed_suggestions:
                sugestao = by_id.get(entry.suggestion_id)
                if sugestao is None:
                    raise ValueError(
                        f"Sugestão {entry.suggestion_id} não pertence ao intake {intake_id}."
                    )
                selected.append((sugestao, entry))
        else:
            selected = [
                (s, ConfirmedSuggestionInput(suggestion_id=s.id))
                for s in intake.sugestoes or []
                if s.review_status != SUGESTAO_REVIEW_REJECTED
            ]

        if not selected:
            raise RuntimeError(
                "Nenhuma sugestão elegível para confirmar o agendamento deste intake."
            )

        confirmed_ids: list[int] = []
        created_task_ids: list[int] = []
        for sugestao, entry in selected:
            target_status = entry.review_status or sugestao.review_status or SUGESTAO_REVIEW_PENDING
            if target_status == SUGESTAO_REVIEW_PENDING:
                target_status = SUGESTAO_REVIEW_APPROVED
            if target_status not in VALID_CONFIRM_REVIEW_STATUSES:
                raise ValueError(
                    f"review_status inválido para confirmação: {target_status!r}."
                )

            sugestao.review_status = target_status
            sugestao.reviewed_by_email = confirmed_by_email
            sugestao.reviewed_at = now
            if entry.created_task_id is not None:
                sugestao.created_task_id = int(entry.created_task_id)
            if sugestao.created_task_id is not None:
                created_task_ids.append(int(sugestao.created_task_id))
            confirmed_ids.append(sugestao.id)

        intake.status = INTAKE_STATUS_SCHEDULED
        intake.error_message = None

        queue_item = None
        if enqueue_legacy_task_cancellation:
            queue_item = self.queue_service.sync_item_from_intake(
                intake,
                commit=False,
                legacy_task_type_external_id=legacy_task_type_external_id,
                legacy_task_subtype_external_id=legacy_task_subtype_external_id,
            )

        self.db.commit()
        self.db.refresh(intake)
        if queue_item is not None:
            self.db.refresh(queue_item)

        return {
            "intake": intake,
            "confirmed_suggestion_ids": confirmed_ids,
            "created_task_ids": created_task_ids,
            "legacy_task_cancellation_item": (
                self.queue_service._item_to_dict(queue_item) if queue_item else None
            ),
        }
