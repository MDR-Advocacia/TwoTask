from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
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
from app.services.prazos_iniciais.legacy_task_circuit_breaker import (
    get_circuit_breaker,
)
from app.services.prazos_iniciais.legacy_task_queue_service import (
    PrazosIniciaisLegacyTaskQueueService,
)
from app.services.prazos_iniciais.legacy_task_queue_worker import (
    get_last_tick_state,
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
    eligible_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    circuit_breaker_tripped: bool = False
    circuit_breaker_tripped_during_tick: bool = False
    tick_id: Optional[str] = None
    items: list[dict]


class QueueItemActionResponse(BaseModel):
    item: dict


class CircuitBreakerResetResponse(BaseModel):
    success: bool = True
    circuit_breaker: dict


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
    intake_id: Optional[int] = Query(default=None, ge=1),
    cnj_number: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(
        default=None,
        description="Filtra itens com updated_at >= since (ISO 8601).",
    ),
    until: Optional[datetime] = Query(
        default=None,
        description="Filtra itens com updated_at <= until (ISO 8601).",
    ),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    items = service.list_items(
        queue_status=queue_status,
        limit=limit,
        intake_id=intake_id,
        cnj_number=cnj_number,
        since=since,
        until=until,
    )
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
    return QueueProcessResponse(
        processed_count=summary.get("processed_count", 0),
        eligible_count=summary.get("eligible_count", 0),
        success_count=summary.get("success_count", 0),
        failure_count=summary.get("failure_count", 0),
        circuit_breaker_tripped=summary.get("circuit_breaker_tripped", False),
        circuit_breaker_tripped_during_tick=summary.get(
            "circuit_breaker_tripped_during_tick", False
        ),
        tick_id=summary.get("tick_id"),
        items=summary.get("items", []),
    )


@router.post(
    "/legacy-task-cancel-queue/circuit-breaker/reset",
    response_model=CircuitBreakerResetResponse,
    summary="Reseta manualmente o circuit breaker do worker (libera o cooldown).",
)
def reset_legacy_task_cancel_circuit_breaker(
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    """
    Zera contador de falhas e libera o cooldown do circuit breaker. Útil quando
    o operador sabe que o Legal One voltou mas o cooldown ainda não venceu — em
    vez de esperar, ele força a próxima execução a rodar normalmente.
    """
    cb = get_circuit_breaker()
    cb.reset()
    snapshot = cb.snapshot()
    return CircuitBreakerResetResponse(
        success=True,
        circuit_breaker={
            "tripped": snapshot.tripped,
            "tripped_until": (
                snapshot.tripped_until.isoformat() if snapshot.tripped_until else None
            ),
            "consecutive_failures": snapshot.consecutive_failures,
            "threshold": snapshot.threshold,
            "cooldown_minutes": snapshot.cooldown_minutes,
            "last_trip_reason": snapshot.last_trip_reason,
            "last_trip_at": (
                snapshot.last_trip_at.isoformat() if snapshot.last_trip_at else None
            ),
            "last_reset_at": (
                snapshot.last_reset_at.isoformat() if snapshot.last_reset_at else None
            ),
            "counted_reasons": list(snapshot.counted_reasons),
        },
    )


@router.get(
    "/legacy-task-cancel-queue/metrics",
    summary="Métricas agregadas da fila de cancelamento + estado do circuit breaker.",
)
def legacy_task_cancel_queue_metrics(
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    payload = service.aggregate_metrics(hours=hours)
    payload["last_tick"] = get_last_tick_state()
    return payload


@router.post(
    "/legacy-task-cancel-queue/items/{item_id}/reprocessar",
    response_model=QueueItemActionResponse,
    summary="Marca um item da fila como PENDENTE pra ser reprocessado pelo worker.",
)
def reprocess_legacy_task_cancel_item(
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    item = service.reprocess_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    return QueueItemActionResponse(item=item)


@router.post(
    "/legacy-task-cancel-queue/items/{item_id}/cancelar",
    response_model=QueueItemActionResponse,
    summary="Cancela manualmente um item da fila (não tenta mais reprocessar).",
)
def cancel_legacy_task_cancel_item(
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    item = service.cancel_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    return QueueItemActionResponse(item=item)


_CSV_COLUMNS = [
    "id",
    "intake_id",
    "queue_status",
    "cnj_number",
    "lawsuit_id",
    "office_id",
    "legacy_task_type_external_id",
    "legacy_task_subtype_external_id",
    "selected_task_id",
    "cancelled_task_id",
    "attempt_count",
    "last_reason",
    "last_attempt_at",
    "completed_at",
    "last_error",
    "created_at",
    "updated_at",
]


@router.get(
    "/legacy-task-cancel-queue/export.csv",
    summary="Exporta itens da fila de cancelamento como CSV (mesmos filtros do GET).",
)
def export_legacy_task_cancel_queue(
    queue_status: Optional[str] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    intake_id: Optional[int] = Query(default=None, ge=1),
    cnj_number: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    items = service.list_items(
        queue_status=queue_status,
        limit=limit,
        intake_id=intake_id,
        cnj_number=cnj_number,
        since=since,
        until=until,
    )

    buffer = io.StringIO()
    # BOM pra Excel reconhecer UTF-8 corretamente.
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in items:
        writer.writerow({col: row.get(col, "") for col in _CSV_COLUMNS})
    buffer.seek(0)

    filename = (
        f"legacy-task-cancel-queue-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    )
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
