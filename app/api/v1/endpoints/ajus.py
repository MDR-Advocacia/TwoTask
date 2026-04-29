"""
Endpoints do módulo AJUS — catálogo de códigos de andamento + fila.

Auth: JWT obrigatório, permissão `prazos_iniciais` (mesmo escopo do
intake — quem trata prazos é quem decide quais andamentos vão pra AJUS).
Operações de catálogo (CRUD de cod_andamento) também respeitam a
permissão; operações destrutivas (delete) podem ser restritas a admin
no futuro.
"""

from __future__ import annotations

import io
import logging
from datetime import date, time
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.ajus import (
    AJUS_QUEUE_PENDENTE,
    AJUS_QUEUE_STATUSES,
    AjusAndamentoQueue,
    AjusClassificacaoQueue,
    AjusCodAndamento,
    AjusSessionAccount,
)
from app.services.ajus.crypto import is_configured as ajus_crypto_configured
from app.services.ajus.session_service import (
    AjusSessionService,
    has_storage_state,
)
from app.models.legal_one import LegalOneUser
from app.services.ajus.classificacao_service import (
    XLSX_HEADERS,
    AjusClassificacaoService,
    XlsxRow,
)
from app.services.ajus.queue_service import (
    MAX_ITENS_POR_REQUEST,
    AjusQueueService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ajus", tags=["AJUS"])


# ═══════════════════════════════════════════════════════════════════════
# Schemas Pydantic
# ═══════════════════════════════════════════════════════════════════════


class CodAndamentoIn(BaseModel):
    codigo: str = Field(..., max_length=64)
    label: str = Field(..., max_length=200)
    descricao: Optional[str] = None
    situacao: str = Field(default="A", pattern="^[AC]$")
    dias_agendamento_offset_uteis: int = Field(default=3, ge=-365, le=365)
    dias_fatal_offset_uteis: int = Field(default=15, ge=-365, le=365)
    informacao_template: str = Field(default="Andamento — processo {cnj}.")
    is_default: bool = False
    is_active: bool = True


class CodAndamentoOut(BaseModel):
    id: int
    codigo: str
    label: str
    descricao: Optional[str]
    situacao: str
    dias_agendamento_offset_uteis: int
    dias_fatal_offset_uteis: int
    informacao_template: str
    is_default: bool
    is_active: bool

    class Config:
        from_attributes = True


class AndamentoQueueOut(BaseModel):
    id: int
    intake_id: int
    cnj_number: str
    cod_andamento_id: int
    cod_andamento_codigo: Optional[str] = None
    cod_andamento_label: Optional[str] = None
    situacao: str
    data_evento: date
    data_agendamento: date
    data_fatal: date
    hora_agendamento: Optional[time]
    informacao: str
    has_pdf: bool
    status: str
    cod_informacao_judicial: Optional[str]
    error_message: Optional[str]
    created_at: str
    dispatched_at: Optional[str]


class AndamentoQueueListResponse(BaseModel):
    total: int
    items: list[AndamentoQueueOut]


class DispatchBatchResponse(BaseModel):
    candidates: int
    success_count: int
    error_count: int
    success_ids: list[int]
    errored: list[dict]


# ═══════════════════════════════════════════════════════════════════════
# Helpers de serialização
# ═══════════════════════════════════════════════════════════════════════


def _queue_to_out(item: AjusAndamentoQueue) -> AndamentoQueueOut:
    cod = item.cod_andamento
    return AndamentoQueueOut(
        id=item.id,
        intake_id=item.intake_id,
        cnj_number=item.cnj_number,
        cod_andamento_id=item.cod_andamento_id,
        cod_andamento_codigo=cod.codigo if cod else None,
        cod_andamento_label=cod.label if cod else None,
        situacao=item.situacao,
        data_evento=item.data_evento,
        data_agendamento=item.data_agendamento,
        data_fatal=item.data_fatal,
        hora_agendamento=item.hora_agendamento,
        informacao=item.informacao,
        has_pdf=bool(item.pdf_path),
        status=item.status,
        cod_informacao_judicial=item.cod_informacao_judicial,
        error_message=item.error_message,
        created_at=item.created_at.isoformat() if item.created_at else "",
        dispatched_at=(
            item.dispatched_at.isoformat() if item.dispatched_at else None
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# Catálogo de códigos de andamento (CRUD)
# ═══════════════════════════════════════════════════════════════════════


@router.get("/cod-andamento", response_model=list[CodAndamentoOut])
def list_cod_andamento(
    only_active: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    q = db.query(AjusCodAndamento)
    if only_active:
        q = q.filter(AjusCodAndamento.is_active.is_(True))
    return [
        CodAndamentoOut.model_validate(c)
        for c in q.order_by(AjusCodAndamento.codigo.asc()).all()
    ]


@router.post(
    "/cod-andamento", response_model=CodAndamentoOut, status_code=201,
)
def create_cod_andamento(
    payload: CodAndamentoIn,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    # Se está marcado como default, garante que nenhum outro fique default
    if payload.is_default:
        db.query(AjusCodAndamento).filter(
            AjusCodAndamento.is_default.is_(True),
        ).update({"is_default": False})
    obj = AjusCodAndamento(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Falha ao criar código (provavelmente duplicado): {exc}",
        ) from exc
    db.refresh(obj)
    return CodAndamentoOut.model_validate(obj)


@router.put("/cod-andamento/{cod_id}", response_model=CodAndamentoOut)
def update_cod_andamento(
    payload: CodAndamentoIn,
    cod_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    obj = db.get(AjusCodAndamento, cod_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Código não encontrado.")
    if payload.is_default and not obj.is_default:
        # Garante que só um seja default
        db.query(AjusCodAndamento).filter(
            AjusCodAndamento.is_default.is_(True),
            AjusCodAndamento.id != cod_id,
        ).update({"is_default": False})
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return CodAndamentoOut.model_validate(obj)


@router.delete("/cod-andamento/{cod_id}", status_code=204)
def delete_cod_andamento(
    cod_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    obj = db.get(AjusCodAndamento, cod_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Código não encontrado.")
    # Bloqueia delete se há itens em fila usando — mantém integridade
    in_use = (
        db.query(AjusAndamentoQueue)
        .filter(AjusAndamentoQueue.cod_andamento_id == cod_id)
        .first()
    )
    if in_use is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Código está em uso por itens da fila — não é possível deletar. "
                "Desative com `is_active=false` se quiser parar de usá-lo."
            ),
        )
    db.delete(obj)
    db.commit()
    return None


# ═══════════════════════════════════════════════════════════════════════
# Fila de andamentos
# ═══════════════════════════════════════════════════════════════════════


@router.get("/andamentos", response_model=AndamentoQueueListResponse)
def list_andamentos(
    status: Optional[str] = Query(default=None, description="CSV de status."),
    cnj_number: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    q = db.query(AjusAndamentoQueue)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        invalid = set(statuses) - AJUS_QUEUE_STATUSES
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Status inválido(s): {sorted(invalid)}",
            )
        if len(statuses) == 1:
            q = q.filter(AjusAndamentoQueue.status == statuses[0])
        else:
            q = q.filter(AjusAndamentoQueue.status.in_(statuses))
    if cnj_number:
        normalized = "".join(c for c in cnj_number if c.isdigit())
        if normalized:
            q = q.filter(AjusAndamentoQueue.cnj_number.like(f"%{normalized}%"))

    total = q.count()
    items = (
        q.order_by(AjusAndamentoQueue.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return AndamentoQueueListResponse(
        total=total,
        items=[_queue_to_out(i) for i in items],
    )


@router.post(
    "/andamentos/dispatch-pending",
    response_model=DispatchBatchResponse,
    summary=(
        "Dispara em lote os próximos N itens em status 'pendente'. "
        f"Limite máximo por chamada: {MAX_ITENS_POR_REQUEST} (limite AJUS)."
    ),
)
def dispatch_pending(
    batch_limit: int = Query(default=MAX_ITENS_POR_REQUEST, ge=1, le=MAX_ITENS_POR_REQUEST),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = AjusQueueService(db)
    result = service.dispatch_pending_batch(batch_limit=batch_limit)
    return DispatchBatchResponse(**result)


@router.post("/andamentos/{item_id}/cancel", response_model=AndamentoQueueOut)
def cancel_andamento(
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = AjusQueueService(db)
    try:
        item = service.cancel(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _queue_to_out(item)


@router.post("/andamentos/{item_id}/retry", response_model=AndamentoQueueOut)
def retry_andamento(
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = AjusQueueService(db)
    try:
        item = service.retry(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _queue_to_out(item)


# ═══════════════════════════════════════════════════════════════════════
# Classificação (Chunk 1 — fila + defaults; Playwright runner no Chunk 2)
# ═══════════════════════════════════════════════════════════════════════


class ClassifDefaultsIn(BaseModel):
    default_matter: Optional[str] = Field(default=None, max_length=255)
    default_risk_loss_probability: Optional[str] = Field(
        default=None, max_length=255,
    )


class ClassifDefaultsOut(BaseModel):
    default_matter: Optional[str]
    default_risk_loss_probability: Optional[str]
    updated_at: Optional[str] = None


class ClassifQueueOut(BaseModel):
    id: int
    cnj_number: str
    intake_id: Optional[int]
    origem: str
    uf: Optional[str]
    comarca: Optional[str]
    matter: Optional[str]
    justice_fee: Optional[str]
    risk_loss_probability: Optional[str]
    status: str
    error_message: Optional[str]
    last_log: Optional[str]
    executed_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class ClassifQueueListResponse(BaseModel):
    total: int
    items: list[ClassifQueueOut]


class ClassifQueueUpdateIn(BaseModel):
    uf: Optional[str] = Field(default=None, max_length=8)
    comarca: Optional[str] = Field(default=None, max_length=255)
    matter: Optional[str] = Field(default=None, max_length=255)
    justice_fee: Optional[str] = Field(default=None, max_length=255)
    risk_loss_probability: Optional[str] = Field(default=None, max_length=255)


class ClassifUploadResponse(BaseModel):
    created: int
    updated: int
    skipped: list[dict]


def _classif_to_out(item: AjusClassificacaoQueue) -> ClassifQueueOut:
    return ClassifQueueOut(
        id=item.id,
        cnj_number=item.cnj_number,
        intake_id=item.intake_id,
        origem=item.origem,
        uf=item.uf,
        comarca=item.comarca,
        matter=item.matter,
        justice_fee=item.justice_fee,
        risk_loss_probability=item.risk_loss_probability,
        status=item.status,
        error_message=item.error_message,
        last_log=item.last_log,
        executed_at=item.executed_at.isoformat() if item.executed_at else None,
        created_at=item.created_at.isoformat() if item.created_at else None,
        updated_at=item.updated_at.isoformat() if item.updated_at else None,
    )


# ── Defaults singleton ──────────────────────────────────────────────


@router.get("/classificacao/defaults", response_model=ClassifDefaultsOut)
def get_classif_defaults(
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    obj = AjusClassificacaoService(db).get_defaults()
    return ClassifDefaultsOut(
        default_matter=obj.default_matter,
        default_risk_loss_probability=obj.default_risk_loss_probability,
        updated_at=obj.updated_at.isoformat() if obj.updated_at else None,
    )


@router.put("/classificacao/defaults", response_model=ClassifDefaultsOut)
def update_classif_defaults(
    payload: ClassifDefaultsIn,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    obj = AjusClassificacaoService(db).update_defaults(
        default_matter=payload.default_matter,
        default_risk_loss_probability=payload.default_risk_loss_probability,
    )
    return ClassifDefaultsOut(
        default_matter=obj.default_matter,
        default_risk_loss_probability=obj.default_risk_loss_probability,
        updated_at=obj.updated_at.isoformat() if obj.updated_at else None,
    )


# ── Lista + detalhe ─────────────────────────────────────────────────


@router.get("/classificacao", response_model=ClassifQueueListResponse)
def list_classif(
    status: Optional[str] = Query(default=None, description="CSV de status."),
    origem: Optional[str] = Query(
        default=None, description="intake_auto | planilha",
    ),
    cnj_search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    statuses: Optional[list[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
    try:
        total, items = AjusClassificacaoService(db).list(
            statuses=statuses,
            origem=origem,
            cnj_search=cnj_search,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ClassifQueueListResponse(
        total=total, items=[_classif_to_out(i) for i in items],
    )


# ── Planilha modelo (download) ─ DECLARADO ANTES DE /{item_id} pra
#    evitar que o validador de int em item_id capture "template.xlsx".


@router.get(
    "/classificacao/template.xlsx",
    summary="Baixa a planilha modelo com cabeçalhos e exemplo.",
)
def download_classif_template(
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    """
    Gera on-the-fly uma planilha modelo com:
      - Linha 1: cabeçalhos (CNJ, UF, Comarca, Matéria, Justiça/Honorário,
        Risco/Probabilidade Perda).
      - Linha 2: exemplo (com valores plausíveis).
      - Aba 'Instruções' explicando preenchimento.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=(
                "openpyxl não instalado no container — adicionar ao "
                "requirements.txt."
            ),
        ) from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Classificações"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F2937")  # cinza escuro
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col_idx, header in enumerate(XLSX_HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    widths = (28, 8, 28, 32, 28, 28)
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + col_idx)].width = width
    ws.row_dimensions[1].height = 30

    ws.cell(row=2, column=1, value="0001234-56.2026.8.05.0001")
    ws.cell(row=2, column=2, value="BA")
    ws.cell(row=2, column=3, value="SALVADOR")
    ws.cell(row=2, column=4, value="Cumprimento de Sentença")
    ws.cell(row=2, column=5, value="Justiça Estadual")
    ws.cell(row=2, column=6, value="Remoto")

    ws_help = wb.create_sheet("Instruções")
    ws_help.column_dimensions["A"].width = 25
    ws_help.column_dimensions["B"].width = 90
    ws_help.cell(row=1, column=1, value="Campo").font = Font(bold=True)
    ws_help.cell(row=1, column=2, value="Como preencher").font = Font(bold=True)

    instr = [
        ("CNJ", "Número do processo (com ou sem máscara)."),
        ("UF", "Sigla da UF (ex.: BA). Se vazio, será derivado do CNJ."),
        ("Comarca", "Nome da comarca (ex.: SALVADOR)."),
        ("Matéria",
         "Texto exato como aparece na capa do AJUS "
         "(ex.: Cumprimento de Sentença)."),
        ("Justiça/Honorário",
         "Texto exato como aparece na capa do AJUS "
         "(ex.: Justiça Estadual / Juizado Especial Cível)."),
        ("Risco/Probabilidade Perda",
         "Texto exato como aparece na capa do AJUS "
         "(ex.: Remoto / Possível / Provável)."),
    ]
    for idx, (campo, desc) in enumerate(instr, start=2):
        ws_help.cell(row=idx, column=1, value=campo)
        c = ws_help.cell(row=idx, column=2, value=desc)
        c.alignment = Alignment(wrap_text=True, vertical="top")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                'attachment; filename="ajus-classificacao-modelo.xlsx"'
            ),
        },
    )


# ── Upload da planilha ─ TAMBÉM declarado antes de /{item_id}.


@router.post(
    "/classificacao/upload-xlsx", response_model=ClassifUploadResponse,
)
async def upload_classif_xlsx(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    """
    Upload da planilha de classificação. Espera os cabeçalhos do
    template (CNJ, UF, Comarca, Matéria, Justiça/Honorário,
    Risco/Probabilidade Perda) na linha 1.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="openpyxl não instalado no container.",
        ) from exc

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    try:
        wb = load_workbook(io.BytesIO(contents), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Falha ao abrir XLSX: {exc}",
        ) from exc

    ws = wb.active
    if ws is None or ws.title.lower().startswith("instru"):
        for sheet in wb.worksheets:
            if not sheet.title.lower().startswith("instru"):
                ws = sheet
                break
    if ws is None:
        raise HTTPException(status_code=400, detail="Nenhuma aba de dados.")

    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    header_norm = [
        (str(h).strip().lower() if h is not None else "")
        for h in header_row
    ]
    expected = [h.lower() for h in XLSX_HEADERS]
    if len(header_norm) < len(expected) or header_norm[: len(expected)] != expected:
        raise HTTPException(
            status_code=422,
            detail=(
                "Cabeçalhos não batem com o template. Esperado: "
                + " | ".join(XLSX_HEADERS)
            ),
        )

    rows: list[XlsxRow] = []
    for raw in ws.iter_rows(min_row=2, values_only=True):
        if raw is None:
            continue
        if all((v is None or str(v).strip() == "") for v in raw):
            continue
        padded = list(raw) + [None] * (len(expected) - len(raw))
        rows.append(
            XlsxRow(
                cnj_number=str(padded[0] or "").strip(),
                uf=(str(padded[1]).strip() if padded[1] is not None else None),
                comarca=(
                    str(padded[2]).strip() if padded[2] is not None else None
                ),
                matter=(
                    str(padded[3]).strip() if padded[3] is not None else None
                ),
                justice_fee=(
                    str(padded[4]).strip() if padded[4] is not None else None
                ),
                risk_loss_probability=(
                    str(padded[5]).strip() if padded[5] is not None else None
                ),
            ),
        )

    if not rows:
        raise HTTPException(status_code=400, detail="Sem linhas de dados.")

    result = AjusClassificacaoService(db).enqueue_from_xlsx_rows(rows)
    return ClassifUploadResponse(**result)


# ═══════════════════════════════════════════════════════════════════════
# Sessões AJUS — multi-conta (Chunk 2a)
# ═══════════════════════════════════════════════════════════════════════


class SessionAccountIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    login: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1)


class SessionAccountUpdateIn(BaseModel):
    label: Optional[str] = Field(default=None, max_length=64)
    login: Optional[str] = Field(default=None, max_length=128)
    password: Optional[str] = None
    is_active: Optional[bool] = None


class SessionAccountOut(BaseModel):
    id: int
    label: str
    login: str
    status: str
    has_storage_state: bool
    has_pending_ip_code: bool
    last_error_message: Optional[str]
    last_error_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool
    created_at: Optional[str]
    updated_at: Optional[str]


class SessionConfigOut(BaseModel):
    crypto_configured: bool
    portal_base_url: str


class IpCodeIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)


def _session_to_out(obj: AjusSessionAccount) -> SessionAccountOut:
    return SessionAccountOut(
        id=obj.id,
        label=obj.label,
        login=obj.login,
        status=obj.status,
        has_storage_state=has_storage_state(obj),
        has_pending_ip_code=bool(obj.pending_ip_code),
        last_error_message=obj.last_error_message,
        last_error_at=(
            obj.last_error_at.isoformat() if obj.last_error_at else None
        ),
        last_used_at=(
            obj.last_used_at.isoformat() if obj.last_used_at else None
        ),
        is_active=obj.is_active,
        created_at=obj.created_at.isoformat() if obj.created_at else None,
        updated_at=obj.updated_at.isoformat() if obj.updated_at else None,
    )


@router.get(
    "/classificacao/sessions/config", response_model=SessionConfigOut,
)
def get_session_config(
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    from app.services.ajus import portal_constants as _portal
    return SessionConfigOut(
        crypto_configured=ajus_crypto_configured(),
        portal_base_url=_portal.PORTAL_BASE_URL,
    )


@router.get(
    "/classificacao/sessions", response_model=list[SessionAccountOut],
)
def list_sessions(
    only_active: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    accounts = AjusSessionService(db).list_accounts(only_active=only_active)
    return [_session_to_out(a) for a in accounts]


@router.post(
    "/classificacao/sessions",
    response_model=SessionAccountOut,
    status_code=201,
)
def create_session(
    payload: SessionAccountIn,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    if not ajus_crypto_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "AJUS_FERNET_KEY não configurada. Adicione a variável "
                "no painel do Coolify antes de cadastrar contas."
            ),
        )
    try:
        obj = AjusSessionService(db).create_account(
            label=payload.label,
            login=payload.login,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=409,
            detail=f"Falha ao criar conta (label duplicado?): {exc}",
        ) from exc
    return _session_to_out(obj)


@router.put(
    "/classificacao/sessions/{account_id}",
    response_model=SessionAccountOut,
)
def update_session(
    payload: SessionAccountUpdateIn,
    account_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    try:
        obj = AjusSessionService(db).update_account(
            account_id,
            label=payload.label,
            login=payload.login,
            password=payload.password,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _session_to_out(obj)


@router.delete(
    "/classificacao/sessions/{account_id}", status_code=204,
)
def delete_session(
    account_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    try:
        AjusSessionService(db).delete_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return None


@router.post(
    "/classificacao/sessions/{account_id}/login",
    response_model=SessionAccountOut,
    summary="Solicita que o runner faça login nessa conta.",
)
def request_login(
    account_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    try:
        obj = AjusSessionService(db).request_login(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _session_to_out(obj)


@router.post(
    "/classificacao/sessions/{account_id}/ip-code",
    response_model=SessionAccountOut,
)
def submit_ip_code(
    payload: IpCodeIn,
    account_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    try:
        obj = AjusSessionService(db).submit_ip_code(account_id, payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _session_to_out(obj)


@router.post(
    "/classificacao/sessions/{account_id}/logout",
    response_model=SessionAccountOut,
)
def request_logout(
    account_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    try:
        obj = AjusSessionService(db).request_logout(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _session_to_out(obj)


# ── Dispatch manual da classificação ───────────────────────────────


class ClassifDispatchOut(BaseModel):
    candidates: int
    success_count: int
    error_count: int
    success_ids: list[int]
    errored: list[dict]
    accounts_used: list[int]


@router.post(
    "/classificacao/dispatch", response_model=ClassifDispatchOut,
    summary=(
        "Dispara processamento manual da fila de classificacao. "
        "Distribui itens pendentes entre as contas online em round-robin. "
        "Util pra testar sem esperar o worker periodico."
    ),
)
def dispatch_classif(
    batch_per_account: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    # Importa lazy — endpoint vive no container API que NÃO tem
    # Playwright; o dispatcher tenta importar o runner e falha graciosamente
    # se for o caso (marca itens como erro). Em prod o operador deve
    # esperar o worker do ajus-runner; esse endpoint serve pra orquestracao.
    from app.services.ajus.classif_dispatcher import AjusClassifDispatcher
    result = AjusClassifDispatcher(db).dispatch_all(
        batch_per_account=batch_per_account,
    )
    return ClassifDispatchOut(
        candidates=result.candidates,
        success_count=result.success_count,
        error_count=result.error_count,
        success_ids=result.success_ids,
        errored=result.errored,
        accounts_used=result.accounts_used,
    )


# ── Detalhe + mutações por item (DEPOIS dos paths estáticos) ────────


@router.get("/classificacao/{item_id}", response_model=ClassifQueueOut)
def get_classif(
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    try:
        item = AjusClassificacaoService(db).get(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _classif_to_out(item)


@router.put("/classificacao/{item_id}", response_model=ClassifQueueOut)
def update_classif(
    payload: ClassifQueueUpdateIn,
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = AjusClassificacaoService(db)
    try:
        item = service.update(
            item_id,
            uf=payload.uf,
            comarca=payload.comarca,
            matter=payload.matter,
            justice_fee=payload.justice_fee,
            risk_loss_probability=payload.risk_loss_probability,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _classif_to_out(item)


@router.post("/classificacao/{item_id}/cancel", response_model=ClassifQueueOut)
def cancel_classif(
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = AjusClassificacaoService(db)
    try:
        item = service.cancel(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _classif_to_out(item)


@router.post("/classificacao/{item_id}/retry", response_model=ClassifQueueOut)
def retry_classif(
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    service = AjusClassificacaoService(db)
    try:
        item = service.retry(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _classif_to_out(item)


# -- Retry em massa --------------------------------------------------


class ClassifRetryBulkIn(BaseModel):
    """
    Se `item_ids` vier, restringe ao conjunto (apenas status=erro sao reenfileirados).
    Se for None, retry em TODOS os itens em status 'erro'.
    """
    item_ids: Optional[list[int]] = None


class ClassifRetryBulkOut(BaseModel):
    retried: int
    ids: list[int]


@router.post(
    "/classificacao/retry-errors",
    response_model=ClassifRetryBulkOut,
    summary=(
        "Retry em massa de itens em status 'erro'. Sem body retoma "
        "todos; com `item_ids` restringe ao conjunto."
    ),
)
def retry_classif_bulk(
    payload: ClassifRetryBulkIn = ClassifRetryBulkIn(),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    result = AjusClassificacaoService(db).retry_errors_bulk(
        item_ids=payload.item_ids,
    )
    return ClassifRetryBulkOut(**result)

