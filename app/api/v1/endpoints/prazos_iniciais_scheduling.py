from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.db.session import SessionLocal
from app.models.legal_one import LegalOneUser
from app.models.prazo_inicial import PrazoInicialIntake
from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
)
from app.services.prazos_iniciais.legacy_task_queue_service import (
    PrazosIniciaisLegacyTaskQueueService,
)
from app.services.prazos_iniciais.scheduling_service import (
    ConfirmedSuggestionInput,
    PrazosIniciaisSchedulingService,
)

router = APIRouter(prefix="/prazos-iniciais", tags=["Prazos Iniciais"])


def _intake_to_summary(intake: PrazoInicialIntake) -> dict:
    return {
        "id": intake.id,
        "external_id": intake.external_id,
        "cnj_number": intake.cnj_number,
        "lawsuit_id": intake.lawsuit_id,
        "office_id": intake.office_id,
        "status": intake.status,
        "natureza_processo": intake.natureza_processo,
        "produto": intake.produto,
        "error_message": intake.error_message,
        "pdf_filename_original": intake.pdf_filename_original,
        "pdf_bytes": intake.pdf_bytes,
        "ged_document_id": intake.ged_document_id,
        "ged_uploaded_at": intake.ged_uploaded_at,
        "received_at": intake.received_at,
        "updated_at": intake.updated_at,
        "sugestoes_count": len(intake.sugestoes or []),
    }


def _process_legacy_task_queue_for_intake(intake_id: int) -> None:
    with SessionLocal() as db:
        service = PrazosIniciaisLegacyTaskQueueService(db)
        service.process_pending_items(limit=1, intake_id=intake_id)


class ConfirmSuggestionPayload(BaseModel):
    suggestion_id: int = Field(..., ge=1)
    created_task_id: Optional[int] = Field(default=None, ge=1)
    review_status: Optional[str] = None


class ConfirmSchedulingRequest(BaseModel):
    suggestions: list[ConfirmSuggestionPayload] = Field(default_factory=list)
    enqueue_legacy_task_cancellation: bool = True
    legacy_task_type_external_id: int = Field(
        default=DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        ge=1,
    )
    legacy_task_subtype_external_id: int = Field(
        default=DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        ge=1,
    )


class ConfirmSchedulingResponse(BaseModel):
    intake: dict
    confirmed_suggestion_ids: list[int]
    created_task_ids: list[int]
    legacy_task_cancellation_item: Optional[dict] = None


class QueueProcessResponse(BaseModel):
    processed_count: int
    items: list[dict]


@router.post(
    "/intakes/{intake_id}/confirmar-agendamento",
    response_model=ConfirmSchedulingResponse,
    summary="Confirma o agendamento do intake e enfileira o cancelamento da task legada.",
)
def confirm_intake_scheduling(
    background_tasks: BackgroundTasks,
    payload: ConfirmSchedulingRequest,
    intake_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(
        auth_security.require_permission("prazos_iniciais")
    ),
):
    service = PrazosIniciaisSchedulingService(db)
    try:
        result = service.confirm_intake_scheduling(
            intake_id=intake_id,
            confirmed_suggestions=[
                ConfirmedSuggestionInput(
                    suggestion_id=item.suggestion_id,
                    created_task_id=item.created_task_id,
                    review_status=item.review_status,
                )
                for item in payload.suggestions
            ]
            or None,
            confirmed_by_email=current_user.email,
            enqueue_legacy_task_cancellation=payload.enqueue_legacy_task_cancellation,
            legacy_task_type_external_id=payload.legacy_task_type_external_id,
            legacy_task_subtype_external_id=payload.legacy_task_subtype_external_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404
        normalized = detail.lower()
        if "inválido" in normalized or "invalido" in normalized:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if payload.enqueue_legacy_task_cancellation:
        background_tasks.add_task(_process_legacy_task_queue_for_intake, intake_id)

    return ConfirmSchedulingResponse(
        intake=_intake_to_summary(result["intake"]),
        confirmed_suggestion_ids=result["confirmed_suggestion_ids"],
        created_task_ids=result["created_task_ids"],
        legacy_task_cancellation_item=result["legacy_task_cancellation_item"],
    )


@router.get(
    "/legacy-task-cancel-queue",
    summary="Lista a fila de cancelamento da task legada de Agendar Prazos.",
)
def list_legacy_task_cancel_queue(
    queue_status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    items = service.list_items(queue_status=queue_status, limit=limit)
    return {
        "total": len(items),
        "items": items,
    }


@router.post(
    "/legacy-task-cancel-queue/process-pending",
    response_model=QueueProcessResponse,
    summary="Processa manualmente itens pendentes da fila de cancelamento legado.",
)
def process_legacy_task_cancel_queue(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    summary = service.process_pending_items(limit=limit)
    return QueueProcessResponse(**summary)
