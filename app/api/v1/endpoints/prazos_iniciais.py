"""
Endpoints do fluxo "Agendar Prazos Iniciais".

Divisão em dois sub-routers:

* `intake_router` — ingresso da automação externa (autenticação por
  API key). Um único endpoint `POST /intake` que aceita multipart
  com o payload JSON + PDF da habilitação.
* `router` — operações internas (JWT + permissão `prazos_iniciais`):
  listagem, detalhe, preview do PDF e controle do ciclo de vida.

O `intake_router` é registrado sem `protected_dependencies` em main.py;
o `router` interno entra no mesmo padrão dos demais (JWT obrigatório).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.config import settings
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneOffice, LegalOneTaskSubType, LegalOneUser
from app.models.prazo_inicial import (
    INTAKE_STATUS_CANCELLED,
    INTAKE_STATUS_LAWSUIT_NOT_FOUND,
    INTAKE_STATUS_RECEIVED,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.models.prazo_inicial_task_template import PrazoInicialTaskTemplate
from app.services.classifier.prazos_iniciais_classifier import (
    PrazosIniciaisBatchClassifier,
)
from app.models.prazo_inicial import (
    INTAKE_STATUS_READY_TO_CLASSIFY,
    PIN_BATCH_STATUS_APPLIED,
    PIN_BATCH_STATUS_FAILED,
    PIN_BATCH_STATUS_IN_PROGRESS,
    PIN_BATCH_STATUS_READY,
    PIN_BATCH_STATUS_SUBMITTED,
    PrazoInicialBatch,
)
from app.services.classifier.prazos_iniciais_schema import (
    TIPO_PRAZO_AUDIENCIA,
    TIPO_PRAZO_JULGAMENTO,
    TIPOS_PRAZO_VALIDOS,
)
from app.services.prazos_iniciais.intake_service import IntakeService
from app.services.prazos_iniciais.storage import (
    PdfValidationError,
    resolve_pdf_path,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Schemas Pydantic
# ═══════════════════════════════════════════════════════════════════════


class ParteProcessual(BaseModel):
    """Representa uma parte do processo (autor ou réu)."""

    nome: str
    documento: Optional[str] = None  # CPF/CNPJ


class CapaProcesso(BaseModel):
    """Dados de capa extraídos pela automação externa."""

    tribunal: Optional[str] = None
    vara: Optional[str] = None
    classe: Optional[str] = None
    assunto: Optional[str] = None
    valor_causa: Optional[float] = None
    data_distribuicao: Optional[date] = None
    polo_ativo: list[ParteProcessual] = Field(default_factory=list)
    polo_passivo: list[ParteProcessual] = Field(default_factory=list)
    segredo_justica: bool = False

    # Permite que a automação envie campos adicionais sem quebrar o contrato.
    class Config:
        extra = "allow"


class PrazoInicialIntakePayload(BaseModel):
    """Body (JSON) do endpoint de ingestão. Acompanha o PDF no multipart."""

    external_id: str = Field(min_length=1, max_length=255)
    cnj_number: str = Field(min_length=1, max_length=32)
    capa: CapaProcesso
    # íntegra em blocos com data — estrutura ainda em definição, aceita qualquer JSON.
    integra_json: dict = Field(default_factory=dict)
    metadata: Optional[dict] = None


class IntakeResponse(BaseModel):
    intake_id: int
    external_id: str
    status: str
    pdf_stored_path: Optional[str] = None
    already_existed: bool = False


class SugestaoOut(BaseModel):
    id: int
    tipo_prazo: str
    subtipo: Optional[str]
    data_base: Optional[date]
    prazo_dias: Optional[int]
    prazo_tipo: Optional[str]
    data_final_calculada: Optional[date]
    audiencia_data: Optional[date]
    audiencia_hora: Optional[str]
    audiencia_link: Optional[str]
    confianca: Optional[str]
    justificativa: Optional[str]
    responsavel_sugerido_id: Optional[int]
    task_type_id: Optional[int]
    task_subtype_id: Optional[int]
    payload_proposto: Optional[dict]
    review_status: str
    reviewed_by_email: Optional[str]
    reviewed_at: Optional[datetime]
    created_task_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class IntakeSummary(BaseModel):
    id: int
    external_id: str
    cnj_number: str
    lawsuit_id: Optional[int]
    office_id: Optional[int]
    status: str
    error_message: Optional[str]
    pdf_filename_original: Optional[str]
    pdf_bytes: Optional[int]
    ged_document_id: Optional[int]
    ged_uploaded_at: Optional[datetime]
    received_at: datetime
    updated_at: datetime
    sugestoes_count: int

    class Config:
        from_attributes = True


class IntakeDetail(IntakeSummary):
    capa_json: dict
    metadata_json: Optional[dict]
    sugestoes: list[SugestaoOut]


class IntakeListResponse(BaseModel):
    total: int
    items: list[IntakeSummary]


# ═══════════════════════════════════════════════════════════════════════
# Intake router (API externa — auth por API key)
# ═══════════════════════════════════════════════════════════════════════

intake_router = APIRouter(prefix="/prazos-iniciais", tags=["Prazos Iniciais"])


def _validate_api_key(
    x_intake_api_key: Optional[str] = Header(default=None, alias="X-Intake-Api-Key"),
) -> str:
    """
    Dependency que autentica a automação externa por header `X-Intake-Api-Key`.

    Aceita múltiplas chaves configuradas em `PRAZOS_INICIAIS_API_KEY`
    (separadas por vírgula) para permitir rotação sem downtime.
    """
    valid_keys = settings.prazos_iniciais_api_keys
    if not valid_keys:
        logger.error(
            "PRAZOS_INICIAIS_API_KEY não configurada — intake rejeitado."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Endpoint de intake não configurado.",
        )
    if not x_intake_api_key or x_intake_api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida ou ausente.",
        )
    return x_intake_api_key


@intake_router.post(
    "/intake",
    response_model=IntakeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Recebe um processo novo da automação externa (multipart).",
)
async def ingest_intake(
    background_tasks: BackgroundTasks,
    payload: str = Form(
        ...,
        description="JSON serializado conforme PrazoInicialIntakePayload.",
    ),
    habilitacao: UploadFile = File(
        ...,
        description="PDF da habilitação nos autos (application/pdf).",
    ),
    _: str = Depends(_validate_api_key),
    db: Session = Depends(get_db),
):
    """
    Recebe um processo novo para a fila de classificação.

    Request: multipart/form-data com:
      - `payload`: JSON serializado com os dados do processo
      - `habilitacao`: PDF da habilitação (≤ PRAZOS_INICIAIS_MAX_PDF_MB)

    Resposta: 202 Accepted em criação nova, 200 OK em reenvio idempotente
    (mesmo `external_id`). Em ambos os casos, o `intake_id` retornado é
    estável para o ciclo de vida do processo.
    """
    # 1. Parse do JSON (o FastAPI já validou que o campo existe, mas é string).
    try:
        payload_dict = json.loads(payload)
        intake_payload = PrazoInicialIntakePayload.model_validate(payload_dict)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campo 'payload' não é JSON válido: {exc}",
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        )

    # 2. Valida MIME declarado (a validação real — magic bytes — é no storage).
    content_type = (habilitacao.content_type or "").lower()
    if content_type and content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Content-Type não suportado: {content_type}. Esperado application/pdf.",
        )

    # 3. Lê os bytes do PDF (com limite defensivo).
    max_bytes = settings.prazos_iniciais_max_pdf_bytes
    pdf_bytes = await habilitacao.read()
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"PDF excede {settings.prazos_iniciais_max_pdf_mb} MB "
                f"(recebido: {len(pdf_bytes)} bytes)."
            ),
        )

    service = IntakeService(db=db)

    # 4. Se já existe, retorna sem reprocessar (mesmo sem ler o PDF adiante).
    existing = service.get_by_external_id(intake_payload.external_id)
    if existing is not None:
        return IntakeResponse(
            intake_id=existing.id,
            external_id=existing.external_id,
            status=existing.status,
            pdf_stored_path=existing.pdf_path,
            already_existed=True,
        )

    # 5. Cria o intake (inclui gravação + validação dos bytes do PDF).
    try:
        result = service.create_intake(
            external_id=intake_payload.external_id,
            cnj_number=intake_payload.cnj_number,
            capa_json=intake_payload.capa.model_dump(mode="json"),
            integra_json=intake_payload.integra_json,
            metadata_json=intake_payload.metadata,
            pdf_bytes=pdf_bytes,
            pdf_filename_original=habilitacao.filename,
        )
    except PdfValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except ValueError as exc:
        # normalize_cnj e afins
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # 6. Dispara resolução do lawsuit em background (não bloqueia a resposta).
    background_tasks.add_task(
        service.resolve_lawsuit_for_intake, result.intake.id
    )

    return IntakeResponse(
        intake_id=result.intake.id,
        external_id=result.intake.external_id,
        status=result.intake.status,
        pdf_stored_path=result.intake.pdf_path,
        already_existed=False,
    )


# ═══════════════════════════════════════════════════════════════════════
# Router interno (JWT + permissão `prazos_iniciais`)
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/prazos-iniciais", tags=["Prazos Iniciais"])


def _intake_to_summary(intake: PrazoInicialIntake) -> IntakeSummary:
    return IntakeSummary(
        id=intake.id,
        external_id=intake.external_id,
        cnj_number=intake.cnj_number,
        lawsuit_id=intake.lawsuit_id,
        office_id=intake.office_id,
        status=intake.status,
        error_message=intake.error_message,
        pdf_filename_original=intake.pdf_filename_original,
        pdf_bytes=intake.pdf_bytes,
        ged_document_id=intake.ged_document_id,
        ged_uploaded_at=intake.ged_uploaded_at,
        received_at=intake.received_at,
        updated_at=intake.updated_at,
        sugestoes_count=len(intake.sugestoes or []),
    )


def _sugestao_to_out(sugestao: PrazoInicialSugestao) -> SugestaoOut:
    return SugestaoOut(
        id=sugestao.id,
        tipo_prazo=sugestao.tipo_prazo,
        subtipo=sugestao.subtipo,
        data_base=sugestao.data_base,
        prazo_dias=sugestao.prazo_dias,
        prazo_tipo=sugestao.prazo_tipo,
        data_final_calculada=sugestao.data_final_calculada,
        audiencia_data=sugestao.audiencia_data,
        audiencia_hora=(
            sugestao.audiencia_hora.strftime("%H:%M")
            if sugestao.audiencia_hora
            else None
        ),
        audiencia_link=sugestao.audiencia_link,
        confianca=sugestao.confianca,
        justificativa=sugestao.justificativa,
        responsavel_sugerido_id=sugestao.responsavel_sugerido_id,
        task_type_id=sugestao.task_type_id,
        task_subtype_id=sugestao.task_subtype_id,
        payload_proposto=sugestao.payload_proposto,
        review_status=sugestao.review_status,
        reviewed_by_email=sugestao.reviewed_by_email,
        reviewed_at=sugestao.reviewed_at,
        created_task_id=sugestao.created_task_id,
        created_at=sugestao.created_at,
    )


@router.get(
    "/intakes",
    response_model=IntakeListResponse,
    summary="Lista intakes com filtros.",
)
def list_intakes(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    office_id: Optional[int] = Query(default=None),
    cnj_number: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    query = db.query(PrazoInicialIntake)
    if status_filter:
        query = query.filter(PrazoInicialIntake.status == status_filter)
    if office_id is not None:
        query = query.filter(PrazoInicialIntake.office_id == office_id)
    if cnj_number:
        # aceita busca por pedaço do CNJ (sem máscara)
        normalized = "".join(c for c in cnj_number if c.isdigit())
        if normalized:
            query = query.filter(
                PrazoInicialIntake.cnj_number.like(f"%{normalized}%")
            )

    total = query.count()
    items = (
        query.order_by(PrazoInicialIntake.received_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return IntakeListResponse(
        total=total,
        items=[_intake_to_summary(item) for item in items],
    )


@router.get(
    "/intakes/{intake_id}",
    response_model=IntakeDetail,
    summary="Detalhe de um intake, com sugestões.",
)
def get_intake(
    intake_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    intake = db.get(PrazoInicialIntake, intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail="Intake não encontrado.")

    summary = _intake_to_summary(intake)
    sugestoes_sorted = sorted(
        intake.sugestoes or [],
        key=lambda s: (s.review_status != "pendente", s.id),
    )
    return IntakeDetail(
        **summary.model_dump(),
        capa_json=intake.capa_json,
        metadata_json=intake.metadata_json,
        sugestoes=[_sugestao_to_out(s) for s in sugestoes_sorted],
    )


@router.get(
    "/intakes/{intake_id}/pdf",
    summary="Stream do PDF da habilitação (preview na UI).",
)
def get_intake_pdf(
    intake_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    intake = db.get(PrazoInicialIntake, intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail="Intake não encontrado.")
    if not intake.pdf_path:
        raise HTTPException(
            status_code=410,
            detail="PDF não está mais disponível localmente (retenção expirada).",
        )

    try:
        absolute = resolve_pdf_path(intake.pdf_path)
    except ValueError:
        logger.error(
            "pdf_path inválido no intake %d: %r", intake_id, intake.pdf_path
        )
        raise HTTPException(status_code=500, detail="Caminho do PDF inválido.")

    if not absolute.exists():
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado.")

    filename = intake.pdf_filename_original or f"habilitacao-{intake_id}.pdf"
    return FileResponse(
        path=absolute,
        media_type="application/pdf",
        filename=filename,
    )


@router.post(
    "/intakes/{intake_id}/reprocessar-cnj",
    response_model=IntakeSummary,
    summary="Força nova tentativa de resolução do lawsuit no L1.",
)
def reprocess_intake_cnj(
    background_tasks: BackgroundTasks,
    intake_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    intake = db.get(PrazoInicialIntake, intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail="Intake não encontrado.")
    if intake.status not in (
        INTAKE_STATUS_LAWSUIT_NOT_FOUND,
        INTAKE_STATUS_RECEIVED,
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Reprocessamento permitido apenas em RECEBIDO / "
                f"PROCESSO_NAO_ENCONTRADO. Status atual: {intake.status}."
            ),
        )
    # Volta pra RECEBIDO pra liberar a resolução.
    intake.status = INTAKE_STATUS_RECEIVED
    intake.error_message = None
    db.commit()
    db.refresh(intake)

    service = IntakeService(db=db)
    background_tasks.add_task(service.resolve_lawsuit_for_intake, intake.id)
    return _intake_to_summary(intake)


@router.post(
    "/intakes/{intake_id}/cancelar",
    response_model=IntakeSummary,
    summary="Cancela manualmente um intake.",
)
def cancel_intake(
    intake_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(
        auth_security.require_permission("prazos_iniciais")
    ),
):
    intake = db.get(PrazoInicialIntake, intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail="Intake não encontrado.")
    intake.status = INTAKE_STATUS_CANCELLED
    intake.error_message = f"Cancelado por {current_user.email}."
    db.commit()
    db.refresh(intake)
    return _intake_to_summary(intake)


# ═══════════════════════════════════════════════════════════════════════
# Trigger e batches de classificação
# ═══════════════════════════════════════════════════════════════════════


class ClassifyPendingResponse(BaseModel):
    submitted: bool
    batch_id: Optional[int] = None
    anthropic_batch_id: Optional[str] = None
    intakes_count: int = 0
    message: str


class BatchSummary(BaseModel):
    id: int
    anthropic_batch_id: Optional[str]
    status: str
    anthropic_status: Optional[str]
    total_records: int
    succeeded_count: int
    errored_count: int
    expired_count: int
    canceled_count: int
    model_used: Optional[str]
    requested_by_email: Optional[str]
    intake_ids: Optional[list[int]]
    created_at: Optional[str]
    submitted_at: Optional[str]
    ended_at: Optional[str]
    applied_at: Optional[str]


class BatchListResponse(BaseModel):
    total: int
    items: list[BatchSummary]


class ApplyBatchResponse(BaseModel):
    succeeded: int
    failed: int
    skipped: int
    total_results: int
    total_sugestoes: int


@router.post(
    "/classificar-pendentes",
    response_model=ClassifyPendingResponse,
    summary="Submete um batch com todos os intakes em PRONTO_PARA_CLASSIFICAR.",
)
async def submit_pending_classification(
    limit: Optional[int] = Query(
        default=None, ge=1, le=500,
        description="Limite opcional de intakes nesta submissão.",
    ),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(
        auth_security.require_permission("prazos_iniciais")
    ),
):
    """
    Coleta intakes em PRONTO_PARA_CLASSIFICAR e dispara um batch da
    Anthropic. Usa Claude Sonnet (configurável em settings).

    Usado tanto pelo botão da UI quanto pelo worker periódico (via call
    direto ao service, sem passar por HTTP).
    """
    classifier = PrazosIniciaisBatchClassifier(db=db)
    cap = limit or settings.prazos_iniciais_batch_max_size
    intakes = classifier.collect_pending_intakes(limit=cap)
    if not intakes:
        return ClassifyPendingResponse(
            submitted=False,
            intakes_count=0,
            message="Nenhum intake em PRONTO_PARA_CLASSIFICAR.",
        )

    try:
        batch = await classifier.submit_batch(
            intakes=intakes,
            requested_by_email=current_user.email,
        )
    except Exception as exc:
        logger.exception("Falha ao submeter batch de prazos iniciais.")
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao enviar batch para Anthropic: {exc}",
        )

    return ClassifyPendingResponse(
        submitted=True,
        batch_id=batch.id,
        anthropic_batch_id=batch.anthropic_batch_id,
        intakes_count=len(intakes),
        message=f"Batch criado com {len(intakes)} intake(s).",
    )


@router.get(
    "/batches",
    response_model=BatchListResponse,
    summary="Lista batches de classificação.",
)
def list_classification_batches(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    classifier = PrazosIniciaisBatchClassifier(db=db)
    batches = classifier.list_batches(limit=limit)
    return BatchListResponse(
        total=len(batches),
        items=[BatchSummary(**classifier.batch_to_dict(b)) for b in batches],
    )


@router.post(
    "/batches/{batch_id}/refresh",
    response_model=BatchSummary,
    summary="Consulta o status de um batch e atualiza contadores.",
)
async def refresh_classification_batch(
    batch_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    classifier = PrazosIniciaisBatchClassifier(db=db)
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")
    if not batch.anthropic_batch_id:
        raise HTTPException(
            status_code=409,
            detail="Batch não tem anthropic_batch_id (provavelmente falhou no submit).",
        )
    try:
        batch = await classifier.refresh_batch_status(batch)
    except Exception as exc:
        logger.exception("Falha ao consultar batch %s", batch_id)
        raise HTTPException(status_code=502, detail=f"Falha ao consultar batch: {exc}")
    return BatchSummary(**classifier.batch_to_dict(batch))


@router.post(
    "/batches/{batch_id}/apply",
    response_model=ApplyBatchResponse,
    summary="Baixa os resultados do batch e materializa as sugestões.",
)
async def apply_classification_batch(
    batch_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    classifier = PrazosIniciaisBatchClassifier(db=db)
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")
    if batch.status == PIN_BATCH_STATUS_APPLIED:
        raise HTTPException(
            status_code=409,
            detail="Batch já foi aplicado; reaplicar exigiria limpar sugestões manualmente.",
        )
    try:
        summary = await classifier.apply_batch_results(batch)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Falha ao aplicar batch %s", batch_id)
        raise HTTPException(status_code=502, detail=f"Falha ao aplicar batch: {exc}")
    return ApplyBatchResponse(**summary)


# ═══════════════════════════════════════════════════════════════════════
# CRUD de Templates (prazo_inicial_task_templates)
# ═══════════════════════════════════════════════════════════════════════
#
# Os templates governam o casamento (tipo_prazo, subtipo, office) → tarefa
# L1. Só admin/operador com permissão `prazos_iniciais` pode tocar. A UI
# de Fase 3c consome estes endpoints.
#
# Regras de validação replicadas na camada HTTP (além da UniqueConstraint
# no banco):
#   - `tipo_prazo` ∈ TIPOS_PRAZO_VALIDOS
#   - `subtipo`:
#       * AUDIENCIA  → {"conciliacao","instrucao","una","outra"} ou None
#       * JULGAMENTO → {"merito","extincao_sem_merito","outro"} ou None
#       * demais tipos → obrigatoriamente None (o casamento do classifier
#         só usa subtipo para AUDIENCIA/JULGAMENTO)
#   - `priority` ∈ {"Low","Normal","High"}
#   - `due_date_reference` ∈ {"data_base","data_final_calculada",
#                             "today","audiencia_data"}
#   - FKs (office_external_id, task_subtype_external_id,
#     responsible_user_external_id) validadas com SELECT antes de
#     persistir, pra devolver 422 com mensagem clara (em vez de deixar
#     estourar IntegrityError no commit).


SUBTIPOS_AUDIENCIA = frozenset({"conciliacao", "instrucao", "una", "outra"})
SUBTIPOS_JULGAMENTO = frozenset({"merito", "extincao_sem_merito", "outro"})
PRIORIDADES_VALIDAS = frozenset({"Low", "Normal", "High"})
DUE_DATE_REFERENCES_VALIDAS = frozenset({
    "data_base",
    "data_final_calculada",
    "today",
    "audiencia_data",
})


class TemplateBase(BaseModel):
    """Campos comuns a create/update — toda validação cruzada vive aqui."""

    name: str = Field(..., min_length=1, max_length=255)
    tipo_prazo: str = Field(..., max_length=64)
    subtipo: Optional[str] = Field(default=None, max_length=128)
    office_external_id: Optional[int] = Field(default=None, ge=1)
    task_subtype_external_id: int = Field(..., ge=1)
    responsible_user_external_id: int = Field(..., ge=1)
    priority: str = Field(default="Normal")
    due_business_days: int = Field(default=3, ge=0, le=365)
    due_date_reference: str = Field(default="data_base")
    description_template: Optional[str] = None
    notes_template: Optional[str] = None
    is_active: bool = True


def _validate_tipo_subtipo(tipo_prazo: str, subtipo: Optional[str]) -> None:
    """Validação cruzada de tipo_prazo × subtipo. Levanta HTTPException 422."""
    if tipo_prazo not in TIPOS_PRAZO_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"tipo_prazo inválido: {tipo_prazo!r}. "
                f"Válidos: {sorted(TIPOS_PRAZO_VALIDOS)}."
            ),
        )
    if tipo_prazo == TIPO_PRAZO_AUDIENCIA:
        if subtipo is not None and subtipo not in SUBTIPOS_AUDIENCIA:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"subtipo inválido para AUDIENCIA: {subtipo!r}. "
                    f"Válidos: {sorted(SUBTIPOS_AUDIENCIA)} ou null."
                ),
            )
    elif tipo_prazo == TIPO_PRAZO_JULGAMENTO:
        if subtipo is not None and subtipo not in SUBTIPOS_JULGAMENTO:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"subtipo inválido para JULGAMENTO: {subtipo!r}. "
                    f"Válidos: {sorted(SUBTIPOS_JULGAMENTO)} ou null."
                ),
            )
    else:
        if subtipo is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"subtipo só é permitido para AUDIENCIA ou JULGAMENTO "
                    f"(tipo_prazo atual: {tipo_prazo}). Envie subtipo=null."
                ),
            )


def _validate_priority_and_due_ref(priority: str, due_ref: str) -> None:
    if priority not in PRIORIDADES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"priority inválida: {priority!r}. "
                f"Válidas: {sorted(PRIORIDADES_VALIDAS)}."
            ),
        )
    if due_ref not in DUE_DATE_REFERENCES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"due_date_reference inválida: {due_ref!r}. "
                f"Válidas: {sorted(DUE_DATE_REFERENCES_VALIDAS)}."
            ),
        )


def _validate_foreign_keys(
    db: Session,
    *,
    office_external_id: Optional[int],
    task_subtype_external_id: int,
    responsible_user_external_id: int,
) -> None:
    """Confirma que os external_ids existem nas tabelas do L1. 422 em caso de ausência."""
    if office_external_id is not None:
        exists = (
            db.query(LegalOneOffice.id)
            .filter(LegalOneOffice.external_id == office_external_id)
            .first()
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"office_external_id não encontrado: {office_external_id}.",
            )

    exists = (
        db.query(LegalOneTaskSubType.id)
        .filter(LegalOneTaskSubType.external_id == task_subtype_external_id)
        .first()
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"task_subtype_external_id não encontrado: "
                f"{task_subtype_external_id}."
            ),
        )

    exists = (
        db.query(LegalOneUser.id)
        .filter(LegalOneUser.external_id == responsible_user_external_id)
        .first()
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"responsible_user_external_id não encontrado: "
                f"{responsible_user_external_id}."
            ),
        )


class TemplateCreate(TemplateBase):
    """Body do POST /prazos-iniciais/templates."""


class TemplateUpdate(BaseModel):
    """
    Body do PATCH /prazos-iniciais/templates/{id}.

    Todos os campos são opcionais — só o que vier é atualizado. Validações
    de tipo/subtipo são re-executadas considerando os valores resultantes
    (os que vieram + os atuais do registro) pra garantir consistência.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    tipo_prazo: Optional[str] = Field(default=None, max_length=64)
    subtipo: Optional[str] = Field(default=None, max_length=128)
    office_external_id: Optional[int] = Field(default=None, ge=1)
    task_subtype_external_id: Optional[int] = Field(default=None, ge=1)
    responsible_user_external_id: Optional[int] = Field(default=None, ge=1)
    priority: Optional[str] = None
    due_business_days: Optional[int] = Field(default=None, ge=0, le=365)
    due_date_reference: Optional[str] = None
    description_template: Optional[str] = None
    notes_template: Optional[str] = None
    is_active: Optional[bool] = None
    # Sentinelas pra permitir explicitamente "setar para NULL" em PATCH.
    # Na prática os campos acima já são Optional; se o cliente quer zerar,
    # manda null. Pra diferenciar "não mexer" de "zerar" usamos
    # `model_fields_set` (Pydantic v2) no handler.

    class Config:
        extra = "forbid"


class TemplateResponse(BaseModel):
    id: int
    name: str
    tipo_prazo: str
    subtipo: Optional[str]
    office_external_id: Optional[int]
    office_name: Optional[str] = None
    task_subtype_external_id: int
    task_subtype_name: Optional[str] = None
    responsible_user_external_id: int
    responsible_user_name: Optional[str] = None
    priority: str
    due_business_days: int
    due_date_reference: str
    description_template: Optional[str]
    notes_template: Optional[str]
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class TemplateListResponse(BaseModel):
    total: int
    items: list[TemplateResponse]


def _template_to_response(
    t: PrazoInicialTaskTemplate,
    *,
    office_name: Optional[str] = None,
    task_subtype_name: Optional[str] = None,
    responsible_user_name: Optional[str] = None,
) -> TemplateResponse:
    return TemplateResponse(
        id=t.id,
        name=t.name,
        tipo_prazo=t.tipo_prazo,
        subtipo=t.subtipo,
        office_external_id=t.office_external_id,
        office_name=office_name,
        task_subtype_external_id=t.task_subtype_external_id,
        task_subtype_name=task_subtype_name,
        responsible_user_external_id=t.responsible_user_external_id,
        responsible_user_name=responsible_user_name,
        priority=t.priority,
        due_business_days=t.due_business_days,
        due_date_reference=t.due_date_reference,
        description_template=t.description_template,
        notes_template=t.notes_template,
        is_active=t.is_active,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _enrich_template_response(
    db: Session, t: PrazoInicialTaskTemplate
) -> TemplateResponse:
    """
    Resolve os nomes legíveis de office / task_subtype / responsável pra
    exibir na UI sem forçar join. Um SELECT por campo (3 queries no pior
    caso) — trivial pra um CRUD de baixa frequência.
    """
    office_name = None
    if t.office_external_id is not None:
        office = (
            db.query(LegalOneOffice.name)
            .filter(LegalOneOffice.external_id == t.office_external_id)
            .first()
        )
        office_name = office[0] if office else None
    sub = (
        db.query(LegalOneTaskSubType.name)
        .filter(LegalOneTaskSubType.external_id == t.task_subtype_external_id)
        .first()
    )
    user = (
        db.query(LegalOneUser.name)
        .filter(LegalOneUser.external_id == t.responsible_user_external_id)
        .first()
    )
    return _template_to_response(
        t,
        office_name=office_name,
        task_subtype_name=sub[0] if sub else None,
        responsible_user_name=user[0] if user else None,
    )


@router.get(
    "/templates",
    response_model=TemplateListResponse,
    summary="Lista templates de tarefa (prazos iniciais), com filtros.",
)
def list_templates(
    tipo_prazo: Optional[str] = Query(default=None),
    subtipo: Optional[str] = Query(default=None),
    office_external_id: Optional[int] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    """
    Lista templates. Filtros opcionais combinam com AND. Ordenação estável
    por (tipo_prazo, subtipo NULLs first, office NULLs last, id) pra
    facilitar leitura na UI de admin.
    """
    q = db.query(PrazoInicialTaskTemplate)
    if tipo_prazo:
        q = q.filter(PrazoInicialTaskTemplate.tipo_prazo == tipo_prazo)
    if subtipo is not None:
        # Cliente mandou string vazia → filtra por subtipo NULL.
        if subtipo == "":
            q = q.filter(PrazoInicialTaskTemplate.subtipo.is_(None))
        else:
            q = q.filter(PrazoInicialTaskTemplate.subtipo == subtipo)
    if office_external_id is not None:
        if office_external_id == 0:
            # Convenção: office_external_id=0 → global (NULL).
            q = q.filter(PrazoInicialTaskTemplate.office_external_id.is_(None))
        else:
            q = q.filter(
                PrazoInicialTaskTemplate.office_external_id == office_external_id
            )
    if is_active is not None:
        q = q.filter(PrazoInicialTaskTemplate.is_active.is_(is_active))

    total = q.count()
    items = (
        q.order_by(
            PrazoInicialTaskTemplate.tipo_prazo.asc(),
            PrazoInicialTaskTemplate.subtipo.asc().nullsfirst(),
            PrazoInicialTaskTemplate.office_external_id.asc().nullslast(),
            PrazoInicialTaskTemplate.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return TemplateListResponse(
        total=total,
        items=[_enrich_template_response(db, t) for t in items],
    )


@router.post(
    "/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um template de tarefa (prazos iniciais).",
)
def create_template(
    body: TemplateCreate,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    _validate_tipo_subtipo(body.tipo_prazo, body.subtipo)
    _validate_priority_and_due_ref(body.priority, body.due_date_reference)
    _validate_foreign_keys(
        db,
        office_external_id=body.office_external_id,
        task_subtype_external_id=body.task_subtype_external_id,
        responsible_user_external_id=body.responsible_user_external_id,
    )

    # Checagem explícita da UniqueConstraint pra devolver 409 clean.
    existing = (
        db.query(PrazoInicialTaskTemplate.id)
        .filter(
            PrazoInicialTaskTemplate.tipo_prazo == body.tipo_prazo,
            (
                PrazoInicialTaskTemplate.subtipo == body.subtipo
                if body.subtipo is not None
                else PrazoInicialTaskTemplate.subtipo.is_(None)
            ),
            (
                PrazoInicialTaskTemplate.office_external_id == body.office_external_id
                if body.office_external_id is not None
                else PrazoInicialTaskTemplate.office_external_id.is_(None)
            ),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Já existe template com (tipo_prazo={body.tipo_prazo}, "
                f"subtipo={body.subtipo}, office_external_id="
                f"{body.office_external_id}). id existente: {existing[0]}."
            ),
        )

    template = PrazoInicialTaskTemplate(
        name=body.name,
        tipo_prazo=body.tipo_prazo,
        subtipo=body.subtipo,
        office_external_id=body.office_external_id,
        task_subtype_external_id=body.task_subtype_external_id,
        responsible_user_external_id=body.responsible_user_external_id,
        priority=body.priority,
        due_business_days=body.due_business_days,
        due_date_reference=body.due_date_reference,
        description_template=body.description_template,
        notes_template=body.notes_template,
        is_active=body.is_active,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _enrich_template_response(db, template)


@router.get(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    summary="Detalhe de um template.",
)
def get_template(
    template_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    template = db.get(PrazoInicialTaskTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    return _enrich_template_response(db, template)


@router.patch(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    summary="Atualiza parcialmente um template (campos omitidos ficam como estão).",
)
def update_template(
    body: TemplateUpdate,
    template_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    template = db.get(PrazoInicialTaskTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template não encontrado.")

    fields_set = body.model_fields_set  # campos realmente enviados

    # ── Resolve valores efetivos (merge do que veio com o atual) ─────
    eff_tipo = body.tipo_prazo if "tipo_prazo" in fields_set else template.tipo_prazo
    eff_subtipo = body.subtipo if "subtipo" in fields_set else template.subtipo
    eff_office = (
        body.office_external_id
        if "office_external_id" in fields_set
        else template.office_external_id
    )
    eff_task_sub = (
        body.task_subtype_external_id
        if "task_subtype_external_id" in fields_set
        else template.task_subtype_external_id
    )
    eff_resp = (
        body.responsible_user_external_id
        if "responsible_user_external_id" in fields_set
        else template.responsible_user_external_id
    )
    eff_priority = body.priority if "priority" in fields_set else template.priority
    eff_due_ref = (
        body.due_date_reference
        if "due_date_reference" in fields_set
        else template.due_date_reference
    )

    _validate_tipo_subtipo(eff_tipo, eff_subtipo)
    _validate_priority_and_due_ref(eff_priority, eff_due_ref)
    # FKs: só valida o que mudou (reduz queries).
    _validate_foreign_keys(
        db,
        office_external_id=(
            eff_office
            if "office_external_id" in fields_set
            else None  # None aqui = não re-valida
        ),
        task_subtype_external_id=eff_task_sub,
        responsible_user_external_id=eff_resp,
    )

    # Conflito de unicidade se a chave (tipo, subtipo, office) mudou.
    key_changed = any(
        k in fields_set for k in ("tipo_prazo", "subtipo", "office_external_id")
    )
    if key_changed:
        conflict = (
            db.query(PrazoInicialTaskTemplate.id)
            .filter(
                PrazoInicialTaskTemplate.id != template_id,
                PrazoInicialTaskTemplate.tipo_prazo == eff_tipo,
                (
                    PrazoInicialTaskTemplate.subtipo == eff_subtipo
                    if eff_subtipo is not None
                    else PrazoInicialTaskTemplate.subtipo.is_(None)
                ),
                (
                    PrazoInicialTaskTemplate.office_external_id == eff_office
                    if eff_office is not None
                    else PrazoInicialTaskTemplate.office_external_id.is_(None)
                ),
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Outro template já ocupa (tipo_prazo={eff_tipo}, "
                    f"subtipo={eff_subtipo}, office_external_id={eff_office}): "
                    f"id={conflict[0]}."
                ),
            )

    # Aplica as mudanças.
    for fname in fields_set:
        setattr(template, fname, getattr(body, fname))

    db.commit()
    db.refresh(template)
    return _enrich_template_response(db, template)


@router.delete(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    summary="Soft-delete de um template (is_active=False).",
)
def delete_template(
    template_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    """
    Soft-delete: marca `is_active=False` em vez de apagar. Templates
    inativos não casam mais sugestões novas, mas permanecem disponíveis
    para auditoria das sugestões antigas que apontam para eles via
    `payload_proposto.template_id`.
    """
    template = db.get(PrazoInicialTaskTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    template.is_active = False
    db.commit()
    db.refresh(template)
    return _enrich_template_response(db, template)
