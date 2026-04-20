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
from app.models.legal_one import LegalOneUser
from app.models.prazo_inicial import (
    INTAKE_STATUS_CANCELLED,
    INTAKE_STATUS_LAWSUIT_NOT_FOUND,
    INTAKE_STATUS_RECEIVED,
    PrazoInicialIntake,
    PrazoInicialSugestao,
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
