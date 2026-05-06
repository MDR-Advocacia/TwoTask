from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, time as dtime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_api_client, get_db
from app.services.legal_one_client import LegalOneApiClient, LegalOneGedUploadError
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prazos-iniciais", tags=["Prazos Iniciais"])


def _run_reprocess_in_background(intake_id: int) -> None:
    """
    Executa o RPA de cancelamento imediatamente, em background, pra um
    intake especifico. Usado pelo botao "Reprocessar" no UI — assim o
    operador nao precisa esperar o tick periodico (~60s).

    Cria propria sessao do banco porque a do request fecha junto com
    a resposta HTTP.
    """
    db = SessionLocal()
    try:
        service = PrazosIniciaisLegacyTaskQueueService(db)
        service.process_pending_items(limit=1, intake_id=intake_id)
    except Exception:
        logger.exception(
            "legacy_task_queue.reprocess_background_failed intake_id=%s",
            intake_id,
        )
    finally:
        db.close()


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
    # Overrides opcionais — quando o operador edita campos da sugestao
    # no modal de Agendar (Modal B). Sao aplicados na sugestao no banco
    # antes de criar a task no L1 (rastreabilidade). Espelha
    # `payload_overrides` em publicacoes.
    override_task_subtype_external_id: Optional[int] = Field(default=None, ge=1)
    override_responsible_user_external_id: Optional[int] = Field(default=None, ge=1)
    override_data_base: Optional[date] = None
    override_data_final_calculada: Optional[date] = None
    # Hora da audiencia editavel pelo operador (HH:MM[:SS]). Vai pro
    # campo `audiencia_hora` da sugestao no banco antes de criar a task
    # no L1. None = manter o valor da IA.
    override_audiencia_hora: Optional[dtime] = None
    override_prazo_dias: Optional[int] = Field(default=None, ge=0, le=365)
    override_prazo_tipo: Optional[str] = None  # util | corrido
    override_priority: Optional[str] = None  # Low | Normal | High
    override_description: Optional[str] = None
    override_notes: Optional[str] = None


class CustomTaskPayload(BaseModel):
    """
    Tarefa avulsa adicionada pelo operador no modal de Confirmar
    Agendamento — nao casa com sugestao da IA. Espelha o padrao de
    "tarefa avulsa" de publicacoes.
    """
    task_subtype_external_id: int = Field(..., ge=1)
    responsible_user_external_id: int = Field(..., ge=1)
    description: str = Field(..., min_length=1)
    due_date: date  # YYYY-MM-DD
    priority: str = Field(default="Normal")
    notes: Optional[str] = None
    # Quando True, o backend redireciona pro assistente da squad do
    # `responsible_user_external_id` via `resolve_assistant`. Equivale ao
    # `target_role='assistente'` no template.
    assign_to_assistant: bool = False


class ConfirmSchedulingRequest(BaseModel):
    suggestions: list[ConfirmSuggestionPayload] = Field(default_factory=list)
    custom_tasks: list[CustomTaskPayload] = Field(default_factory=list)
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
    from app.services.prazos_iniciais.scheduling_service import (
        CustomTaskInput as _CustomTaskInput,
    )

    service = PrazosIniciaisSchedulingService(db)
    try:
        result = service.confirm_intake_scheduling(
            intake_id=intake_id,
            confirmed_suggestions=[
                ConfirmedSuggestionInput(
                    suggestion_id=item.suggestion_id,
                    created_task_id=item.created_task_id,
                    review_status=item.review_status,
                    override_task_subtype_external_id=item.override_task_subtype_external_id,
                    override_responsible_user_external_id=item.override_responsible_user_external_id,
                    override_data_base=item.override_data_base,
                    override_data_final_calculada=item.override_data_final_calculada,
                    override_audiencia_hora=item.override_audiencia_hora,
                    override_prazo_dias=item.override_prazo_dias,
                    override_prazo_tipo=item.override_prazo_tipo,
                    override_priority=item.override_priority,
                    override_description=item.override_description,
                    override_notes=item.override_notes,
                )
                for item in payload.suggestions
            ]
            or None,
            custom_tasks=[
                _CustomTaskInput(
                    task_subtype_external_id=ct.task_subtype_external_id,
                    responsible_user_external_id=ct.responsible_user_external_id,
                    description=ct.description,
                    due_date=ct.due_date,
                    priority=ct.priority,
                    notes=ct.notes,
                    assign_to_assistant=ct.assign_to_assistant,
                )
                for ct in payload.custom_tasks
            ]
            or None,
            confirmed_by_email=current_user.email,
            confirmed_by_user_id=current_user.id,
            confirmed_by_name=getattr(current_user, "name", None),
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

    # Onda 3 #5 — Disparo desacoplado: GED + cancel da legada NÃO são
    # acionados aqui. O intake fica AGENDADO + dispatch_pending=True. O
    # operador (ou worker periódico) aciona via /dispatch-treatment-web.
    return ConfirmSchedulingResponse(
        intake=_intake_to_summary(result["intake"]),
        confirmed_suggestion_ids=result["confirmed_suggestion_ids"],
        created_task_ids=result["created_task_ids"],
        legacy_task_cancellation_item=result["legacy_task_cancellation_item"],
    )


# ────────────────────────────────────────────────────────────────
# Finalizar sem providência (Caminho A)
# ────────────────────────────────────────────────────────────────


class FinalizeWithoutProvidenceRequest(BaseModel):
    """
    Body do POST /intakes/{id}/finalizar-sem-providencia.
    `notes` é opcional e vai pra `metadata_json.finalize_without_providence`
    pra trilha de auditoria (quem finalizou e por quê).
    """
    notes: Optional[str] = Field(default=None, max_length=500)
    enqueue_legacy_task_cancellation: bool = True
    legacy_task_type_external_id: int = Field(
        default=DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        ge=1,
    )
    legacy_task_subtype_external_id: int = Field(
        default=DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        ge=1,
    )


class FinalizeWithoutProvidenceResponse(BaseModel):
    intake: dict
    legacy_task_cancellation_item: Optional[dict] = None


@router.post(
    "/intakes/{intake_id}/finalizar-sem-providencia",
    response_model=FinalizeWithoutProvidenceResponse,
    summary=(
        "Finaliza o intake SEM criar tarefa no Legal One. Sobe habilitação "
        "pro GED, cancela task legada, marca CONCLUIDO_SEM_PROVIDENCIA."
    ),
)
def finalize_without_providence(
    background_tasks: BackgroundTasks,
    payload: FinalizeWithoutProvidenceRequest,
    intake_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(
        auth_security.require_permission("prazos_iniciais")
    ),
):
    service = PrazosIniciaisSchedulingService(db)
    try:
        result = service.finalize_without_scheduling(
            intake_id=intake_id,
            confirmed_by_email=current_user.email,
            confirmed_by_user_id=current_user.id,
            confirmed_by_name=getattr(current_user, "name", None),
            notes=payload.notes,
            enqueue_legacy_task_cancellation=payload.enqueue_legacy_task_cancellation,
            legacy_task_type_external_id=payload.legacy_task_type_external_id,
            legacy_task_subtype_external_id=payload.legacy_task_subtype_external_id,
        )
    except ValueError as exc:
        # intake não encontrado
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        # status inválido OU falha no GED
        detail = str(exc)
        # 422 pra status inválido (regra de negócio), 502 pra falha do L1
        status_code = 502 if "Legal One" in detail or "GED" in detail else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc

    # Onda 3 #5 — Disparo desacoplado: GED + cancel não são acionados
    # aqui. Intake fica CONCLUIDO_SEM_PROVIDENCIA + dispatch_pending=True.
    return FinalizeWithoutProvidenceResponse(
        intake=_intake_to_summary(result["intake"]),
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
    summary="Reprocessa um item da fila imediatamente (em background).",
)
def reprocess_legacy_task_cancel_item(
    background_tasks: BackgroundTasks,
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisLegacyTaskQueueService(db)
    item = service.reprocess_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    # Dispara o RPA imediatamente em background — operador nao precisa
    # esperar o tick periodico (~60s) do worker. A resposta HTTP retorna
    # rapido com o item ja em PENDING; o cancelamento real acontece
    # logo em seguida em outra thread.
    intake_id = item.get("intake_id") if isinstance(item, dict) else None
    if intake_id:
        background_tasks.add_task(_run_reprocess_in_background, int(intake_id))

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


# ────────────────────────────────────────────────────────────────
# Onda 3 #5 — Dispatch Treatment Web (desacoplado)
# ────────────────────────────────────────────────────────────────

class DispatchTreatmentWebResponse(BaseModel):
    """Resposta do POST /intakes/{id}/dispatch-treatment-web.

    `skipped` indica que o intake já estava com dispatch_pending=False
    (idempotente). `intake` traz o estado atualizado.
    """
    intake: dict
    legacy_task_cancellation_item: Optional[dict] = None
    skipped: bool = False
    reason: Optional[str] = None


@router.post(
    "/intakes/{intake_id}/dispatch-treatment-web",
    response_model=DispatchTreatmentWebResponse,
    summary=(
        "Dispara o tratamento web (GED upload + enqueue cancel da legacy) "
        "de um intake AGENDADO/CONCLUIDO_SEM_PROVIDENCIA."
    ),
)
def dispatch_treatment_web(
    background_tasks: BackgroundTasks,
    intake_id: int = Path(..., ge=1),
    legacy_task_type_external_id: int = Query(
        default=DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID, ge=1,
    ),
    legacy_task_subtype_external_id: int = Query(
        default=DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID, ge=1,
    ),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = PrazosIniciaisSchedulingService(db)
    try:
        result = service.dispatch_treatment_web(
            intake_id=intake_id,
            legacy_task_type_external_id=legacy_task_type_external_id,
            legacy_task_subtype_external_id=legacy_task_subtype_external_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        detail = str(exc)
        # Falhas de Legal One/GED viram 502 (upstream); resto é regra
        # de negócio (status incompatível, lawsuit_id ausente).
        status_code = 502 if (
            "Legal One" in detail or "GED" in detail or "enfileirar" in detail
        ) else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc

    # Após disparo, processa imediatamente a fila daquele intake em
    # background pra encurtar latência percebida pelo operador.
    if not result.get("skipped"):
        background_tasks.add_task(_process_legacy_task_queue_for_intake, intake_id)

    return DispatchTreatmentWebResponse(
        intake=_intake_to_summary(result["intake"]),
        legacy_task_cancellation_item=result.get("legacy_task_cancellation_item"),
        skipped=bool(result.get("skipped", False)),
        reason=result.get("reason"),
    )


@router.post(
    "/intakes/dispatch-pending/process-batch",
    summary=(
        "Dispara em lote os intakes com dispatch_pending=True (idempotente, "
        "ordem cronológica). batch_limit controla quantos por chamada."
    ),
)
def dispatch_pending_intakes_batch(
    background_tasks: BackgroundTasks,
    batch_limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    """Endpoint usado tanto pelo botão "Disparar todos" da Tratamento Web
    quanto pelo worker periódico (Onda 3 #6)."""
    from app.models.prazo_inicial import PrazoInicialIntake

    pending_ids = (
        db.query(PrazoInicialIntake.id)
        .filter(PrazoInicialIntake.dispatch_pending.is_(True))
        .order_by(PrazoInicialIntake.treated_at.asc().nullslast())
        .limit(batch_limit)
        .all()
    )
    intake_ids = [row[0] for row in pending_ids]

    service = PrazosIniciaisSchedulingService(db)
    success: list[int] = []
    failed: list[dict] = []
    skipped: list[int] = []

    for iid in intake_ids:
        try:
            result = service.dispatch_treatment_web(intake_id=iid)
            if result.get("skipped"):
                skipped.append(iid)
            else:
                success.append(iid)
                background_tasks.add_task(
                    _process_legacy_task_queue_for_intake, iid,
                )
        except Exception as exc:  # noqa: BLE001
            failed.append({"intake_id": iid, "error": str(exc)[:300]})
            # Loop continua — falhas individuais não interrompem o lote.
            continue

    return {
        "candidates": len(intake_ids),
        "success_count": len(success),
        "skipped_count": len(skipped),
        "failure_count": len(failed),
        "success_ids": success,
        "skipped_ids": skipped,
        "failed": failed,
    }


# ─── Debug: GED upload via ECM API ─────────────────────────────
# Rota isolada pra testar o fluxo ECM API (GET getcontainer -> PUT
# Azure Blob -> POST /documents) com qualquer PDF e qualquer litigation,
# sem precisar agendar intake real. Util pra mapear novos typeIds
# ("type_N") em outras instancias L1 ou validar correcoes futuras.

@router.post("/debug/ged-upload")
async def debug_ged_upload(
    litigation_id: int = Form(..., description="ID do processo (Litigation) no L1"),
    type_id: Optional[str] = Form(None, description="typeId formato literal 'type_N' (ex.: 'type_48' = Habilitação, 'type_5' = Certidão). Omitir cria sem tipo. Catalogo completo: ver comentario em legal_one_client.upload_document_to_ged."),
    archive_name: Optional[str] = Form(None, description="Nome visivel do arquivo (default: nome enviado)"),
    description: Optional[str] = Form(None, description="Descricao livre"),
    notes: Optional[str] = Form(None, description="Observacoes livres"),
    file: UploadFile = File(..., description="PDF a enviar"),
    client: LegalOneApiClient = Depends(get_api_client),
    _=Depends(auth_security.get_current_user),
):
    """
    Testa o fluxo ECM API end-to-end com um PDF arbitrario.

    Retorna `{document_id, file_name_sent, archive_sent}` em caso de sucesso,
    ou `{error, detail}` com 502 e o corpo do erro do L1 em caso de falha.
    Os deltas GET->PUT e PUT->POST aparecem no log do container (procurar
    por `delta_get_to_put_ms` e `delta_put_to_post_ms`).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome.")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    try:
        document_id = client.upload_document_to_ged(
            file_bytes=file_bytes,
            file_name=file.filename,
            type_id=type_id,
            litigation_id=litigation_id,
            archive_name=archive_name,
            description=description,
            notes=notes,
        )
    except LegalOneGedUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "document_id": document_id,
        "file_name_sent": file.filename,
        "archive_sent": archive_name or file.filename,
        "size_bytes": len(file_bytes),
        "litigation_id": litigation_id,
        "type_id": type_id,
    }
