"""Endpoints do modulo Classificador (diagnostico de carteira).

Fase 2 (corrente):
- POST /classificador/lotes (upload xlsx) — implementado
- POST /classificador/lotes/from-prazos-iniciais — implementado
- POST /classificador/lotes/from-prazos-iniciais/preview — implementado
- GET /classificador/lotes (listagem paginada) — implementado
- GET /classificador/lotes/{id} (detalhe) — implementado
- GET /classificador/lotes/{id}/processos (drill-down paginado) — implementado
- DELETE /classificador/lotes/{id} (cancelar/apagar) — implementado

Fase 3 (proxima):
- POST /classificador/lotes/{id}/capture-l1 (refresh L1 async)
- POST /classificador/lotes/{id}/classify (batch Anthropic)

Fase 4:
- POST /classificador/lotes/{id}/relatorios (gerar xlsx/pdf async)
- GET /classificador/lotes/{id}/relatorios/{id}/download
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.classificador import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_READY,
    ClassificadorBatch,
    ClassificadorLote,
    ClassificadorProcesso,
    ClassificadorRelatorio,
    LOTE_STATUS_CANCELLED,
    LOTE_STATUS_CLASSIFIED,
    LOTE_STATUS_CLASSIFYING,
)
from app.models.legal_one import LegalOneUser
from app.services.classificador.classifier_runner import (
    ClassificadorBatchClassifier,
)
from app.services.classificador.intake_service import (
    IntakeError,
    create_lote_from_prazos_iniciais,
    create_lote_from_upload,
    preview_from_prazos_iniciais,
)
from app.services.classificador.pdf_intake import (
    PdfIntakeError,
    SOURCE_PDF_UPLOAD,
    ingest_pdf,
)
from app.services.classificador.report_data import build_report_data
from app.services.classificador.report_storage import (
    resolve_report_path,
    save_report,
)
from app.services.classificador.report_pdf import generate_pdf_report
from app.services.classificador.report_xlsx import generate_xlsx_report
from app.services.classificador.xlsx_reader import XlsxHeaderError
from app.services.prazos_iniciais.storage import PdfValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classificador", tags=["Classificador"])

# Router separado pro intake publico — SEM dependencies JWT, auth via
# header X-Classificador-Api-Key. Registrado em main.py SEM
# protected_dependencies pra nao herdar JWT requirement.
intake_router = APIRouter(prefix="/classificador", tags=["Classificador - Intake API"])


def _validate_classificador_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-Classificador-Api-Key"),
) -> str:
    """Dependency que valida X-Classificador-Api-Key contra settings.

    Aceita multiplas chaves (rotacao sem downtime) via env var
    CLASSIFICADOR_API_KEY (separadas por virgula).
    """
    from app.core.config import settings

    valid_keys = settings.classificador_api_keys
    if not valid_keys:
        logger.error("CLASSIFICADOR_API_KEY nao configurada — intake rejeitado.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Endpoint de intake do Classificador nao configurado.",
        )
    if not x_api_key or x_api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key invalida ou ausente.",
        )
    return x_api_key


@intake_router.post(
    "/intake/pdf",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Recebe 1 PDF de processo do robo de entrega (fila dormente).",
)
def intake_pdf(
    file: UploadFile = File(..., description="PDF do processo completo"),
    cliente_nome: Optional[str] = Form(default=None),
    external_id: Optional[str] = Form(default=None),
    cnj_hint: Optional[str] = Form(default=None),
    produto: Optional[str] = Form(default=None),
    observacao: Optional[str] = Form(default=None),
    metadata_json: Optional[str] = Form(
        default=None, description="JSON serializado pra contexto livre"
    ),
    _: str = Depends(_validate_classificador_api_key),
    db: Session = Depends(get_db),
):
    """Recebe 1 PDF e insere na fila do worker dormente.

    NAO cria lote imediatamente — o worker `pending_worker` agrupa em
    batches de 50 (por cliente_nome) e dispara ingest_pdf + classify
    automaticamente.

    Retorna 202 Accepted + pending_id pra rastreabilidade.

    Idempotencia opcional via pdf_sha256 — se mesmo sha ja chegou em
    PENDENTE/ALOCADO, devolve o pending_id existente.
    """
    import json as _json
    from app.models.classificador import (
        ClassificadorPdfPending,
        PENDING_STATUS_PENDENTE,
    )
    from app.services.classificador.pdf_intake import SOURCE_PDF_ROBOT_API
    from app.services.prazos_iniciais.storage import (
        PdfValidationError,
        save_pdf,
    )

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    from app.core.config import settings as _s2
    if len(content) > _s2.prazos_iniciais_max_pdf_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo maior que {_s2.prazos_iniciais_max_pdf_mb}MB.",
        )

    # 1) Salva PDF no volume (valida magic bytes + tamanho)
    try:
        stored = save_pdf(content)
    except PdfValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 2) Idempotencia por sha256 — devolve o pending existente se ja vier
    existing = (
        db.query(ClassificadorPdfPending)
        .filter(ClassificadorPdfPending.pdf_sha256 == stored.sha256)
        .filter(ClassificadorPdfPending.status.in_({"PENDENTE", "ALOCADO"}))
        .order_by(ClassificadorPdfPending.id.desc())
        .first()
    )
    if existing:
        return {
            "pending_id": existing.id,
            "status": existing.status,
            "duplicate": True,
            "received_at": existing.received_at.isoformat() if existing.received_at else None,
        }

    # 3) Parse metadata_json (opcional)
    meta_dict = None
    if metadata_json:
        try:
            meta_dict = _json.loads(metadata_json)
        except _json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="metadata_json invalido (nao e' JSON valido).",
            )

    # 4) Insere na fila
    pending = ClassificadorPdfPending(
        pdf_path=stored.relative_path,
        pdf_sha256=stored.sha256,
        pdf_bytes=stored.size_bytes,
        pdf_filename_original=file.filename or "pending.pdf",
        cliente_nome=(cliente_nome or "").strip() or None,
        external_id=(external_id or "").strip() or None,
        cnj_hint=(cnj_hint or "").strip() or None,
        produto=(produto or "").strip() or None,
        observacao=(observacao or "").strip() or None,
        source=SOURCE_PDF_ROBOT_API,
        metadata_json=meta_dict,
        status=PENDING_STATUS_PENDENTE,
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)

    logger.info(
        "Classificador.intake: pending=#%s sha=%s cliente=%r (fila aguardando worker)",
        pending.id, stored.sha256[:8], pending.cliente_nome,
    )
    return {
        "pending_id": pending.id,
        "status": pending.status,
        "duplicate": False,
        "received_at": pending.received_at.isoformat() if pending.received_at else None,
    }


@router.get("/pending/metrics")
def get_pending_metrics(db: Session = Depends(get_db)):
    """Metricas da fila do motor dormente — PDFs/dia, tempo medio, status."""
    from datetime import datetime as _dt, timedelta as _td
    from sqlalchemy import func
    from app.models.classificador import (
        ClassificadorPdfPending,
        PENDING_STATUS_ALOCADO,
        PENDING_STATUS_ERRO,
        PENDING_STATUS_PENDENTE,
        PENDING_STATUS_PROCESSADO,
    )

    now = _dt.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    d7 = now - _td(days=7)
    d30 = now - _td(days=30)

    # Counts por status
    status_rows = (
        db.query(ClassificadorPdfPending.status, func.count(ClassificadorPdfPending.id))
        .group_by(ClassificadorPdfPending.status)
        .all()
    )
    status_counts = {s: int(c) for s, c in status_rows}

    # PDFs/dia (received_at)
    pdfs_hoje = (
        db.query(func.count(ClassificadorPdfPending.id))
        .filter(ClassificadorPdfPending.received_at >= today_start)
        .scalar() or 0
    )
    pdfs_7d = (
        db.query(func.count(ClassificadorPdfPending.id))
        .filter(ClassificadorPdfPending.received_at >= d7)
        .scalar() or 0
    )
    pdfs_30d = (
        db.query(func.count(ClassificadorPdfPending.id))
        .filter(ClassificadorPdfPending.received_at >= d30)
        .scalar() or 0
    )

    # Tempo medio: received → allocated (seg). So pega entries com allocated_at != null
    rows_alloc = (
        db.query(ClassificadorPdfPending.received_at, ClassificadorPdfPending.allocated_at)
        .filter(ClassificadorPdfPending.allocated_at.isnot(None))
        .filter(ClassificadorPdfPending.received_at >= d30)
        .all()
    )
    if rows_alloc:
        avg_alloc_sec = sum(
            (alloc - rcv).total_seconds() for rcv, alloc in rows_alloc
        ) / len(rows_alloc)
    else:
        avg_alloc_sec = None

    # Tempo medio: allocated → processed
    rows_proc = (
        db.query(ClassificadorPdfPending.allocated_at, ClassificadorPdfPending.processed_at)
        .filter(ClassificadorPdfPending.allocated_at.isnot(None))
        .filter(ClassificadorPdfPending.processed_at.isnot(None))
        .filter(ClassificadorPdfPending.received_at >= d30)
        .all()
    )
    if rows_proc:
        avg_proc_sec = sum(
            (proc - alloc).total_seconds() for alloc, proc in rows_proc
        ) / len(rows_proc)
    else:
        avg_proc_sec = None

    # Taxa de erro = ERRO / (ERRO + PROCESSADO)
    erro = status_counts.get(PENDING_STATUS_ERRO, 0)
    proc = status_counts.get(PENDING_STATUS_PROCESSADO, 0)
    total_finalizado = erro + proc
    taxa_erro = (erro / total_finalizado) if total_finalizado > 0 else None

    # Pendentes mais antigos (age max)
    oldest = (
        db.query(func.min(ClassificadorPdfPending.received_at))
        .filter(ClassificadorPdfPending.status == PENDING_STATUS_PENDENTE)
        .scalar()
    )
    oldest_age_sec = (now - oldest).total_seconds() if oldest else None

    return {
        "status_counts": {
            "pendente": status_counts.get(PENDING_STATUS_PENDENTE, 0),
            "alocado": status_counts.get(PENDING_STATUS_ALOCADO, 0),
            "processado": status_counts.get(PENDING_STATUS_PROCESSADO, 0),
            "erro": status_counts.get(PENDING_STATUS_ERRO, 0),
        },
        "throughput": {
            "pdfs_hoje": int(pdfs_hoje),
            "pdfs_7d": int(pdfs_7d),
            "pdfs_30d": int(pdfs_30d),
            "media_diaria_30d": round(pdfs_30d / 30, 1) if pdfs_30d else 0,
        },
        "latencia_segundos": {
            "media_fila_para_lote": round(avg_alloc_sec, 1) if avg_alloc_sec else None,
            "media_lote_para_processado": round(avg_proc_sec, 1) if avg_proc_sec else None,
            "pendente_mais_antigo": round(oldest_age_sec, 1) if oldest_age_sec else None,
        },
        "taxa_erro": round(taxa_erro, 4) if taxa_erro is not None else None,
        "generated_at": now.isoformat(),
    }


@router.get("/pending")
def list_pending(
    status_filter: Optional[str] = Query(None, alias="status"),
    cliente_nome: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista a fila de PDFs pendentes (operador vê o que o robô entregou)."""
    from app.models.classificador import ClassificadorPdfPending

    q = db.query(ClassificadorPdfPending).order_by(
        ClassificadorPdfPending.received_at.desc()
    )
    if status_filter:
        q = q.filter(ClassificadorPdfPending.status == status_filter)
    if cliente_nome:
        q = q.filter(ClassificadorPdfPending.cliente_nome.ilike(f"%{cliente_nome}%"))

    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return {
        "total": total,
        "items": [
            {
                "id": p.id,
                "pdf_filename_original": p.pdf_filename_original,
                "pdf_sha256": p.pdf_sha256,
                "pdf_bytes": p.pdf_bytes,
                "cliente_nome": p.cliente_nome,
                "external_id": p.external_id,
                "cnj_hint": p.cnj_hint,
                "produto": p.produto,
                "source": p.source,
                "status": p.status,
                "lote_id": p.lote_id,
                "processo_id": p.processo_id,
                "error_message": p.error_message,
                "received_at": p.received_at.isoformat() if p.received_at else None,
                "allocated_at": p.allocated_at.isoformat() if p.allocated_at else None,
                "processed_at": p.processed_at.isoformat() if p.processed_at else None,
            }
            for p in items
        ],
    }


# ─── Pydantic schemas (request bodies) ────────────────────────────────


class FromPrazosIniciaisFiltros(BaseModel):
    """Filtros pra importar intakes de Prazos Iniciais como lote."""

    data_inicio: Optional[date] = Field(
        default=None, description="Inclusivo. Filtra por received_at >="
    )
    data_fim: Optional[date] = Field(
        default=None, description="Inclusivo. Filtra por received_at <="
    )
    office_id: Optional[int] = Field(default=None, description="Escritorio Legal One")
    cliente_nome_match: Optional[str] = Field(
        default=None, description="Match parcial em external_id (legacy)"
    )
    statuses: Optional[list[str]] = Field(
        default=None,
        description="Lista de status de intake aceitos. Default = tratados.",
    )


class FromPrazosIniciaisPayload(BaseModel):
    nome: str = Field(..., min_length=1, max_length=255)
    cliente_nome: Optional[str] = Field(default=None, max_length=255)
    descricao: Optional[str] = None
    filtros: FromPrazosIniciaisFiltros
    # Modo UPSERT: se informado, atualiza esse lote existente em vez de criar
    merge_into_lote_id: Optional[int] = Field(
        default=None,
        description="Se preenchido, atualiza esse lote em vez de criar novo (UPSERT por source_intake_id)",
    )
    reset_classification: bool = Field(
        default=False,
        description="Quando merge: limpa campos da IA e marca PRONTO_PARA_CLASSIFICAR",
    )


# ─── Helpers ──────────────────────────────────────────────────────────


def _serialize_lote(lote: ClassificadorLote) -> dict:
    """Serializa lote pra resposta JSON. Mantem floats pra Decimal."""
    return {
        "id": lote.id,
        "nome": lote.nome,
        "cliente_nome": lote.cliente_nome,
        "descricao": lote.descricao,
        "status": lote.status,
        "source_summary": lote.source_summary,
        "filtros_aplicados": lote.filtros_aplicados,
        "total_processos": lote.total_processos,
        "total_processos_capturados": lote.total_processos_capturados,
        "total_processos_classificados": lote.total_processos_classificados,
        "total_processos_com_erro": lote.total_processos_com_erro,
        "valor_total_causa": (
            float(lote.valor_total_causa) if lote.valor_total_causa is not None else None
        ),
        "valor_total_estimado": (
            float(lote.valor_total_estimado)
            if lote.valor_total_estimado is not None
            else None
        ),
        "pcond_total": (
            float(lote.pcond_total) if lote.pcond_total is not None else None
        ),
        "prob_exito_medio": (
            float(lote.prob_exito_medio) if lote.prob_exito_medio is not None else None
        ),
        "analise_estrategica_carteira": lote.analise_estrategica_carteira,
        "snapshot_at": lote.snapshot_at.isoformat() if lote.snapshot_at else None,
        "captura_l1_started_at": (
            lote.captura_l1_started_at.isoformat()
            if lote.captura_l1_started_at
            else None
        ),
        "captura_l1_finished_at": (
            lote.captura_l1_finished_at.isoformat()
            if lote.captura_l1_finished_at
            else None
        ),
        "classificacao_started_at": (
            lote.classificacao_started_at.isoformat()
            if lote.classificacao_started_at
            else None
        ),
        "classificacao_finished_at": (
            lote.classificacao_finished_at.isoformat()
            if lote.classificacao_finished_at
            else None
        ),
        "error_message": lote.error_message,
        "created_at": lote.created_at.isoformat() if lote.created_at else None,
        "created_by_user_id": lote.created_by_user_id,
    }


# ─── Lotes ────────────────────────────────────────────────────────────


@router.get("/lotes")
def list_lotes(
    status_filter: Optional[str] = Query(None, alias="status"),
    cliente_nome: Optional[str] = Query(None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista paginada dos lotes — mais recente primeiro."""
    q = db.query(ClassificadorLote).order_by(ClassificadorLote.created_at.desc())
    if status_filter:
        q = q.filter(ClassificadorLote.status == status_filter)
    if cliente_nome:
        like = f"%{cliente_nome}%"
        q = q.filter(ClassificadorLote.cliente_nome.ilike(like))

    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return {
        "total": total,
        "items": [_serialize_lote(lote) for lote in items],
    }


@router.post("/lotes", status_code=status.HTTP_201_CREATED)
def create_lote_upload(
    nome: str = Form(...),
    cliente_nome: Optional[str] = Form(default=None),
    descricao: Optional[str] = Form(default=None),
    file: UploadFile = File(..., description="Planilha .xlsx com coluna CNJ"),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Cria lote a partir de upload xlsx.

    Form fields:
    - `nome` (obrig.): nome do diagnostico/lote
    - `cliente_nome` (opcional): nome do cliente final (vai pra capa do relatorio)
    - `descricao` (opcional): contexto
    - `file` (obrig.): planilha xlsx com coluna 'CNJ' (ou alias)

    Validacoes:
    - Content-type aceito: xlsx + qualquer (UploadFile e' tolerante)
    - Tamanho max: settings.prazos_iniciais_max_pdf_mb (default 200MB)
    - Header obrigatorio: cnj (na linha 1 ou 2)
    """
    # Limite de tamanho (reusa setting compartilhado)
    content = file.file.read()
    from app.core.config import settings as _s
    if len(content) > _s.prazos_iniciais_max_pdf_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo maior que {_s.prazos_iniciais_max_pdf_mb}MB.",
        )

    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    try:
        lote, warnings = create_lote_from_upload(
            db,
            nome=nome,
            cliente_nome=cliente_nome,
            descricao=descricao,
            file_filename=file.filename or "upload.xlsx",
            file_content=content,
            created_by_user_id=current_user.id if current_user else None,
        )
    except XlsxHeaderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao criar lote a partir de xlsx.")
        raise HTTPException(
            status_code=500, detail=f"Erro inesperado: {type(exc).__name__}: {exc}"
        )

    return {
        "lote": _serialize_lote(lote),
        "warnings": warnings,
    }


@router.post("/lotes/from-prazos-iniciais", status_code=status.HTTP_201_CREATED)
def create_lote_from_prazos_iniciais_endpoint(
    payload: FromPrazosIniciaisPayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Cria lote espelhando intakes de Prazos Iniciais que casam com os filtros.

    Body: { nome, cliente_nome?, descricao?, filtros: { data_inicio?, data_fim?, office_id?, statuses? } }
    """
    try:
        lote, merge_stats = create_lote_from_prazos_iniciais(
            db,
            nome=payload.nome,
            cliente_nome=payload.cliente_nome,
            descricao=payload.descricao,
            data_inicio=payload.filtros.data_inicio,
            data_fim=payload.filtros.data_fim,
            office_id=payload.filtros.office_id,
            cliente_nome_match=payload.filtros.cliente_nome_match,
            statuses=payload.filtros.statuses,
            created_by_user_id=current_user.id if current_user else None,
            merge_into_lote_id=payload.merge_into_lote_id,
            reset_classification=payload.reset_classification,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao criar/atualizar lote a partir de Prazos Iniciais.")
        raise HTTPException(
            status_code=500, detail=f"Erro inesperado: {type(exc).__name__}: {exc}"
        )

    response = {"lote": _serialize_lote(lote)}
    if merge_stats:
        response["merge_stats"] = merge_stats
    return response


@router.post("/lotes/from-prazos-iniciais/preview")
def preview_lote_from_prazos_iniciais(
    filtros: FromPrazosIniciaisFiltros,
    db: Session = Depends(get_db),
):
    """Preview: conta quantos intakes casam + sample dos 5 mais recentes.

    Usado pra UI mostrar 'Vai criar lote com N processos. Confirmar?'
    antes de submeter o POST /from-prazos-iniciais.
    """
    return preview_from_prazos_iniciais(
        db,
        data_inicio=filtros.data_inicio,
        data_fim=filtros.data_fim,
        office_id=filtros.office_id,
        cliente_nome_match=filtros.cliente_nome_match,
        statuses=filtros.statuses,
    )


@router.get("/lotes/{lote_id}")
def get_lote(lote_id: int, db: Session = Depends(get_db)):
    """Detalhe de um lote — sem processos (vide /lotes/{id}/processos)."""
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")
    return _serialize_lote(lote)


@router.delete("/lotes/{lote_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lote(
    lote_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Cancela/apaga um lote.

    Lotes ja CLASSIFICADOS nao podem ser apagados (sao documentos
    historicos). Use cancel se ainda nao terminou. Apos classificado,
    so admin via SQL.
    """
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    if lote.status == LOTE_STATUS_CLASSIFIED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Lote ja CLASSIFICADO e' documento historico — nao pode "
                "ser deletado via UI. Use SQL admin se realmente necessario."
            ),
        )

    if lote.status == LOTE_STATUS_CLASSIFYING:
        # In-flight — marca como CANCELADO em vez de deletar
        lote.status = LOTE_STATUS_CANCELLED
        lote.error_message = (
            f"Cancelado pelo usuario {current_user.id} durante classificacao."
            if current_user
            else "Cancelado durante classificacao."
        )
        db.commit()
        return

    # Caso comum (RASCUNHO, CAPTURANDO_L1, READY, ERRO): apaga
    db.delete(lote)
    db.commit()


@router.get("/lotes/{lote_id}/filter-options")
def get_filter_options(lote_id: int, db: Session = Depends(get_db)):
    """Lista valores DISTINCT presentes nos processos do lote — pra popular
    selects de filtro na UI (categoria, produto, natureza, patrocinio).

    Patrocinio e' extraido de patrocinio_json.decisao em Python (JSON
    nao indexado em distinct facil).
    """
    from sqlalchemy import distinct, func

    from app.models.classification_taxonomy import ClassificationCategory

    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    # Categorias distintas presentes (JOIN pra ter o nome)
    cat_rows = (
        db.query(
            ClassificadorProcesso.categoria_id,
            ClassificationCategory.name,
        )
        .join(
            ClassificationCategory,
            ClassificationCategory.id == ClassificadorProcesso.categoria_id,
        )
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.categoria_id.isnot(None))
        .distinct()
        .order_by(ClassificationCategory.name)
        .all()
    )
    categorias = [
        {"id": r[0], "nome": r[1]} for r in cat_rows
    ]

    # Produtos / naturezas distintos (campos diretos)
    produtos = [
        r[0]
        for r in db.query(distinct(ClassificadorProcesso.produto))
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.produto.isnot(None))
        .order_by(ClassificadorProcesso.produto)
        .all()
    ]
    naturezas = [
        r[0]
        for r in db.query(distinct(ClassificadorProcesso.natureza_processo))
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.natureza_processo.isnot(None))
        .order_by(ClassificadorProcesso.natureza_processo)
        .all()
    ]

    # Patrocinio: extrai de patrocinio_json
    patrocinios_set = set()
    rows = (
        db.query(ClassificadorProcesso.patrocinio_json)
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.patrocinio_json.isnot(None))
        .all()
    )
    for (p_json,) in rows:
        if isinstance(p_json, dict):
            if not p_json.get("aplicavel"):
                patrocinios_set.add("NAO_APLICAVEL")
            elif p_json.get("decisao"):
                patrocinios_set.add(p_json["decisao"])
    # Default sempre presente pra dar opcao mesmo sem dado
    patrocinios = sorted(patrocinios_set)

    return {
        "categorias": categorias,
        "produtos": produtos,
        "naturezas": naturezas,
        "patrocinios": patrocinios,
    }


@router.get("/dashboard-global/filter-options")
def get_global_filter_options(db: Session = Depends(get_db)):
    """Distintos GLOBAIS (cross-lote) pra popular selects do painel global.

    Inclui categorias, produtos, naturezas, ufs (extraidos do tribunal) e
    patrocinios (das decisoes em patrocinio_json).
    """
    import re
    from sqlalchemy import distinct
    from app.models.classification_taxonomy import ClassificationCategory

    cat_rows = (
        db.query(ClassificadorProcesso.categoria_id, ClassificationCategory.name)
        .join(ClassificationCategory,
              ClassificationCategory.id == ClassificadorProcesso.categoria_id)
        .filter(ClassificadorProcesso.categoria_id.isnot(None))
        .distinct()
        .order_by(ClassificationCategory.name)
        .all()
    )
    categorias = [{"id": r[0], "nome": r[1]} for r in cat_rows]

    produtos = [
        r[0] for r in db.query(distinct(ClassificadorProcesso.produto))
        .filter(ClassificadorProcesso.produto.isnot(None))
        .order_by(ClassificadorProcesso.produto)
        .all()
    ]

    naturezas = [
        r[0] for r in db.query(distinct(ClassificadorProcesso.natureza_processo))
        .filter(ClassificadorProcesso.natureza_processo.isnot(None))
        .order_by(ClassificadorProcesso.natureza_processo)
        .all()
    ]

    # UFs / tribunais — extrai da capa
    _tj_re = re.compile(r"^TJ([A-Z]{2})$", re.IGNORECASE)
    ufs_set = set()
    tribunais_set = set()
    rows = (
        db.query(ClassificadorProcesso.capa_json)
        .filter(ClassificadorProcesso.capa_json.isnot(None))
        .all()
    )
    for (capa,) in rows:
        if isinstance(capa, dict):
            trib = (capa.get("tribunal") or "").strip().upper()
            if trib:
                tribunais_set.add(trib)
                m = _tj_re.match(trib)
                if m:
                    ufs_set.add(m.group(1))
                elif trib.startswith("TR") or trib in ("TST", "STJ", "STF"):
                    ufs_set.add(trib)
    ufs = sorted(ufs_set)
    tribunais = sorted(tribunais_set)

    # Patrocinios distintos
    patroc_set = set()
    rows = (
        db.query(ClassificadorProcesso.patrocinio_json)
        .filter(ClassificadorProcesso.patrocinio_json.isnot(None))
        .all()
    )
    for (p_json,) in rows:
        if isinstance(p_json, dict):
            if not p_json.get("aplicavel"):
                patroc_set.add("NAO_APLICAVEL")
            elif p_json.get("decisao"):
                patroc_set.add(p_json["decisao"])
    patrocinios = sorted(patroc_set)

    # Clientes distintos
    clientes = [
        r[0] for r in db.query(distinct(ClassificadorLote.cliente_nome))
        .filter(ClassificadorLote.cliente_nome.isnot(None))
        .order_by(ClassificadorLote.cliente_nome)
        .all()
    ]

    return {
        "categorias": categorias,
        "produtos": produtos,
        "naturezas": naturezas,
        "ufs": ufs,
        "tribunais": tribunais,
        "patrocinios": patrocinios,
        "clientes": clientes,
    }


@router.get("/dashboard-global")
def get_dashboard_global(
    cliente_nome: Optional[str] = Query(None),
    start: Optional[date] = Query(None, description="created_at >="),
    end: Optional[date] = Query(None, description="created_at <="),
    only_classified: bool = Query(False, description="se true, so lotes CLASSIFICADO"),
    categoria_id: Optional[int] = Query(None),
    produto: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    patrocinio: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Dashboard agregado CROSS-LOTE — somatorio de todos os lotes que
    casam com os filtros.

    Filtros de LOTE: cliente_nome, start/end (created_at), only_classified.
    Filtros de PROCESSO (afetam as agregacoes mas mantem lista de lotes):
    categoria_id, produto, uf, patrocinio.

    Otimizado via SQL aggregates (sum/count/avg) — nao carrega processos
    individuais em Python. Pra carteira de 100 lotes × 6k processos =
    600k rows, fica em ~300ms.
    """
    from datetime import timedelta as _td

    from sqlalchemy import and_, func, or_

    # Query base — lotes que casam com filtros
    q_lote = db.query(ClassificadorLote)
    if cliente_nome:
        q_lote = q_lote.filter(
            ClassificadorLote.cliente_nome.ilike(f"%{cliente_nome}%")
        )
    if start:
        q_lote = q_lote.filter(ClassificadorLote.created_at >= start)
    if end:
        q_lote = q_lote.filter(
            ClassificadorLote.created_at < (end + _td(days=1))
        )
    if only_classified:
        q_lote = q_lote.filter(ClassificadorLote.status == "CLASSIFICADO")

    lotes = q_lote.order_by(ClassificadorLote.created_at.desc()).all()
    if not lotes:
        return {
            "total_lotes": 0,
            "kpis": {},
            "por_categoria": [],
            "por_patrocinio": [],
            "lotes": [],
            "timeline": [],
            "generated_at": datetime.utcnow().isoformat(),
        }

    lote_ids = [l.id for l in lotes]

    # KPIs globais (soma das somas)
    kpi = (
        db.query(
            func.sum(ClassificadorLote.total_processos),
            func.sum(ClassificadorLote.total_processos_classificados),
            func.sum(ClassificadorLote.total_processos_com_erro),
            func.sum(ClassificadorLote.valor_total_causa),
            func.sum(ClassificadorLote.valor_total_estimado),
            func.sum(ClassificadorLote.pcond_total),
            func.avg(ClassificadorLote.prob_exito_medio),
        )
        .filter(ClassificadorLote.id.in_(lote_ids))
        .first()
    )

    def _f(v):
        return float(v) if v is not None else None

    kpis = {
        "total_processos": int(kpi[0] or 0),
        "total_classificados": int(kpi[1] or 0),
        "total_com_erro": int(kpi[2] or 0),
        "valor_total_causa": _f(kpi[3]),
        "valor_total_estimado": _f(kpi[4]),
        "pcond_total": _f(kpi[5]),
        "prob_exito_medio": _f(kpi[6]),
    }

    # Por categoria (cross-lote, agregado em SQL)
    from app.models.classification_taxonomy import ClassificationCategory

    # Filtros opcionais a nivel de processo
    def _apply_proc_filters(query):
        if categoria_id is not None:
            query = query.filter(ClassificadorProcesso.categoria_id == categoria_id)
        if produto:
            query = query.filter(ClassificadorProcesso.produto == produto)
        if patrocinio:
            if patrocinio == "NAO_APLICAVEL":
                query = query.filter(
                    or_(
                        ClassificadorProcesso.patrocinio_json.is_(None),
                        ClassificadorProcesso.patrocinio_json.op("->>")("aplicavel")
                        == "false",
                    )
                )
            else:
                query = query.filter(
                    ClassificadorProcesso.patrocinio_json.op("->>")("decisao")
                    == patrocinio
                )
        # UF: filtra pelo prefixo do tribunal (TJSP, TJRJ, etc.) ou tribunal direto
        if uf:
            uf_upper = uf.upper()
            # Tenta capa_json->>'tribunal' = TJ<UF> ou == tribunal
            query = query.filter(
                or_(
                    ClassificadorProcesso.capa_json.op("->>")("tribunal") == f"TJ{uf_upper}",
                    ClassificadorProcesso.capa_json.op("->>")("tribunal") == uf_upper,
                )
            )
        return query

    cat_q = (
        db.query(
            ClassificationCategory.name,
            func.count(ClassificadorProcesso.id),
            func.sum(ClassificadorProcesso.valor_estimado),
            func.sum(ClassificadorProcesso.pcond_sugerido),
            func.avg(ClassificadorProcesso.prob_exito),
        )
        .outerjoin(
            ClassificationCategory,
            ClassificationCategory.id == ClassificadorProcesso.categoria_id,
        )
        .filter(ClassificadorProcesso.lote_id.in_(lote_ids))
    )
    cat_q = _apply_proc_filters(cat_q)
    cat_rows = (
        cat_q
        .group_by(ClassificationCategory.name)
        .order_by(func.count(ClassificadorProcesso.id).desc())
        .all()
    )
    por_categoria = [
        {
            "label": r[0] or "(sem categoria)",
            "qtd": int(r[1] or 0),
            "valor_estimado": _f(r[2]),
            "pcond": _f(r[3]),
            "prob_exito_medio": _f(r[4]),
        }
        for r in cat_rows
    ]

    # Por patrocinio — itera em Python (JSON em SQLite sem indice)
    from collections import defaultdict
    patroc_acc: dict[str, dict] = defaultdict(
        lambda: {"qtd": 0, "valor_estimado": 0.0, "pcond": 0.0}
    )
    patroc_q = (
        db.query(
            ClassificadorProcesso.patrocinio_json,
            ClassificadorProcesso.valor_estimado,
            ClassificadorProcesso.pcond_sugerido,
        )
        .filter(ClassificadorProcesso.lote_id.in_(lote_ids))
    )
    patroc_q = _apply_proc_filters(patroc_q)
    rows = patroc_q.all()
    for (p_json, ve, pc) in rows:
        if isinstance(p_json, dict) and p_json.get("aplicavel"):
            label = p_json.get("decisao") or "INDETERMINADO"
        else:
            label = "NAO_APLICAVEL"
        d = patroc_acc[label]
        d["qtd"] += 1
        if ve is not None:
            d["valor_estimado"] += float(ve)
        if pc is not None:
            d["pcond"] += float(pc)
    por_patrocinio = [
        {"label": k, "qtd": v["qtd"],
         "valor_estimado": v["valor_estimado"], "pcond": v["pcond"]}
        for k, v in sorted(
            patroc_acc.items(), key=lambda kv: -kv[1]["qtd"],
        )
    ]

    # Lista de lotes (ranking)
    lotes_payload = [
        {
            "id": l.id,
            "nome": l.nome,
            "cliente_nome": l.cliente_nome,
            "status": l.status,
            "total_processos": l.total_processos or 0,
            "total_classificados": l.total_processos_classificados or 0,
            "valor_total_estimado": _f(l.valor_total_estimado),
            "pcond_total": _f(l.pcond_total),
            "prob_exito_medio": _f(l.prob_exito_medio),
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in lotes
    ]

    # Timeline — lotes por dia
    timeline_map: dict[str, dict] = defaultdict(
        lambda: {"qtd_lotes": 0, "qtd_processos": 0, "valor": 0.0, "pcond": 0.0}
    )
    for l in lotes:
        if not l.created_at:
            continue
        key = l.created_at.date().isoformat()
        d = timeline_map[key]
        d["qtd_lotes"] += 1
        d["qtd_processos"] += l.total_processos or 0
        if l.valor_total_estimado is not None:
            d["valor"] += float(l.valor_total_estimado)
        if l.pcond_total is not None:
            d["pcond"] += float(l.pcond_total)
    timeline = [
        {"date": k, **v}
        for k, v in sorted(timeline_map.items())
    ]

    return {
        "total_lotes": len(lotes),
        "kpis": kpis,
        "por_categoria": por_categoria,
        "por_patrocinio": por_patrocinio,
        "lotes": lotes_payload,
        "timeline": timeline,
        "generated_at": datetime.utcnow().isoformat(),
        "filtros": {
            "cliente_nome": cliente_nome,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "only_classified": only_classified,
        },
    }


@router.get("/lotes/{lote_id}/dashboard-data")
def get_dashboard_data(
    lote_id: int,
    db: Session = Depends(get_db),
):
    """Payload agregado pro Dashboard interativo (recharts) do lote.

    Reusa `report_data.build_report_data` (mesmo agregador usado pro
    XLSX/PDF) — retorna KPIs + recortes por categoria/patrocinio/produto/
    UF/tribunal + top 10 + pedidos por tipo + sentencas/transito.

    Sem cache — payload e' barato (<200ms pra carteira de 6k processos).
    Se ficar lento em prod, adicionar cache em redis com TTL 60s.
    """
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    try:
        data = build_report_data(db, lote_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Classificador.dashboard: falha agregando lote=%s", lote_id)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao agregar dados: {type(exc).__name__}: {exc}",
        )

    # Remove campos pesados que nao sao usados pelo dashboard (economiza
    # bytes na resposta; usuario pode acessar via processos/detalhe).
    data.pop("processos", None)
    data.pop("pedidos", None)
    return data


@router.get("/lotes/{lote_id}/processos/{processo_id}")
def get_processo_detail(
    lote_id: int,
    processo_id: int,
    db: Session = Depends(get_db),
):
    """Detalhe completo de 1 processo dentro do lote — com pedidos +
    nomes resolvidos de categoria/subcategoria (JOIN).

    Reuso da estrutura do `_serialize_lote` mas pra processos. Retorna
    TODOS os campos pro Drawer renderizar agrupado por secao.
    """
    from app.models.classificador import ClassificadorPedido
    from app.models.classification_taxonomy import (
        ClassificationCategory,
        ClassificationSubcategory,
    )

    proc = (
        db.query(ClassificadorProcesso)
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.id == processo_id)
        .first()
    )
    if proc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Processo #{processo_id} nao encontrado no lote #{lote_id}.",
        )

    # Resolve nomes categoria/subcategoria
    cat_nome = None
    if proc.categoria_id:
        cat = (
            db.query(ClassificationCategory)
            .filter(ClassificationCategory.id == proc.categoria_id)
            .first()
        )
        cat_nome = cat.name if cat else None
    sub_nome = None
    if proc.subcategoria_id:
        sub = (
            db.query(ClassificationSubcategory)
            .filter(ClassificationSubcategory.id == proc.subcategoria_id)
            .first()
        )
        sub_nome = sub.name if sub else None

    # Pedidos 1:N
    pedidos = (
        db.query(ClassificadorPedido)
        .filter(ClassificadorPedido.processo_id == processo_id)
        .order_by(ClassificadorPedido.id.asc())
        .all()
    )

    def _f(v):
        return float(v) if v is not None else None

    return {
        "id": proc.id,
        "lote_id": proc.lote_id,
        "source": proc.source,
        "source_intake_id": proc.source_intake_id,
        "cnj_number": proc.cnj_number,
        "lawsuit_id": proc.lawsuit_id,
        "external_id": proc.external_id,

        # Capa + integra
        "capa_json": proc.capa_json,
        "polo_ativo": proc.polo_ativo,
        "polo_passivo": proc.polo_passivo,
        "integra_json": proc.integra_json,
        "metadata_json": proc.metadata_json,
        "natureza_processo": proc.natureza_processo,
        "produto": proc.produto,

        # Patrocinio (snapshot)
        "patrocinio_json": proc.patrocinio_json,

        # Classificacao IA
        "categoria_id": proc.categoria_id,
        "categoria_nome": cat_nome,
        "subcategoria_id": proc.subcategoria_id,
        "subcategoria_nome": sub_nome,
        "polo": proc.polo,
        "valor_estimado": _f(proc.valor_estimado),
        "pcond_sugerido": _f(proc.pcond_sugerido),
        "prob_exito": _f(proc.prob_exito),
        "justificativa": proc.justificativa,
        "analise_estrategica": proc.analise_estrategica,
        "confianca": _f(proc.confianca),

        # Bloco completo da IA (pra ler sentenca/transito/primeira_hab/etc)
        "classificacao_response_json": proc.classificacao_response_json,
        "contestacao_existente_json": proc.contestacao_existente_json,

        # PDF + extracao mecanica
        "pdf_path": proc.pdf_path,
        "pdf_sha256": proc.pdf_sha256,
        "pdf_bytes": proc.pdf_bytes,
        "pdf_filename_original": proc.pdf_filename_original,
        "pdf_extraction_failed": proc.pdf_extraction_failed,
        "extractor_used": proc.extractor_used,
        "extraction_confidence": proc.extraction_confidence,

        # Status + timestamps
        "status": proc.status,
        "error_message": proc.error_message,
        "classification_batch_id": proc.classification_batch_id,
        "data_captura_l1": proc.data_captura_l1.isoformat() if proc.data_captura_l1 else None,
        "data_classificacao": proc.data_classificacao.isoformat() if proc.data_classificacao else None,
        "created_at": proc.created_at.isoformat() if proc.created_at else None,
        "updated_at": proc.updated_at.isoformat() if proc.updated_at else None,

        # Pedidos (1:N)
        "pedidos": [
            {
                "id": p.id,
                "tipo_pedido": p.tipo_pedido,
                "natureza": p.natureza,
                "valor_indicado": _f(p.valor_indicado),
                "valor_estimado": _f(p.valor_estimado),
                "fundamentacao_valor": p.fundamentacao_valor,
                "probabilidade_perda": p.probabilidade_perda,
                "aprovisionamento": _f(p.aprovisionamento),
                "fundamentacao_risco": p.fundamentacao_risco,
            }
            for p in pedidos
        ],
    }


@router.get("/lotes/{lote_id}/processos")
def list_processos(
    lote_id: int,
    status_filter: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None),
    categoria_id: Optional[int] = Query(None),
    polo: Optional[str] = Query(None),
    cnj_match: Optional[str] = Query(None),
    produto: Optional[str] = Query(None),
    natureza_processo: Optional[str] = Query(None),
    patrocinio: Optional[str] = Query(
        None,
        description="MDR_ADVOCACIA|OUTRO_ESCRITORIO|CONDUCAO_INTERNA|NAO_APLICAVEL",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista paginada de processos do lote.

    Filtros: status, source, categoria, polo, cnj, produto, natureza, patrocinio.
    """
    from sqlalchemy import or_

    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    q = (
        db.query(ClassificadorProcesso)
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .order_by(ClassificadorProcesso.id.asc())
    )
    if status_filter:
        q = q.filter(ClassificadorProcesso.status == status_filter)
    if source:
        q = q.filter(ClassificadorProcesso.source == source)
    if categoria_id is not None:
        q = q.filter(ClassificadorProcesso.categoria_id == categoria_id)
    if polo:
        q = q.filter(ClassificadorProcesso.polo == polo)
    if cnj_match:
        q = q.filter(ClassificadorProcesso.cnj_number.ilike(f"%{cnj_match}%"))
    if produto:
        q = q.filter(ClassificadorProcesso.produto == produto)
    if natureza_processo:
        q = q.filter(ClassificadorProcesso.natureza_processo == natureza_processo)
    if patrocinio:
        # Patrocinio.json e' JSON — extrai via op('->>') (Postgres + SQLite OK)
        if patrocinio == "NAO_APLICAVEL":
            q = q.filter(
                or_(
                    ClassificadorProcesso.patrocinio_json.is_(None),
                    ClassificadorProcesso.patrocinio_json.op("->>")("aplicavel")
                    == "false",
                )
            )
        else:
            q = q.filter(
                ClassificadorProcesso.patrocinio_json.op("->>")("decisao")
                == patrocinio
            )

    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return {
        "total": total,
        "items": [
            {
                "id": p.id,
                "lote_id": p.lote_id,
                "source": p.source,
                "source_intake_id": p.source_intake_id,
                "cnj_number": p.cnj_number,
                "external_id": p.external_id,
                "produto": p.produto,
                "categoria_id": p.categoria_id,
                "subcategoria_id": p.subcategoria_id,
                "polo": p.polo,
                "valor_estimado": (
                    float(p.valor_estimado) if p.valor_estimado is not None else None
                ),
                "pcond_sugerido": (
                    float(p.pcond_sugerido) if p.pcond_sugerido is not None else None
                ),
                "prob_exito": (
                    float(p.prob_exito) if p.prob_exito is not None else None
                ),
                "confianca": (
                    float(p.confianca) if p.confianca is not None else None
                ),
                "status": p.status,
                "error_message": p.error_message,
                "data_captura_l1": (
                    p.data_captura_l1.isoformat() if p.data_captura_l1 else None
                ),
                "data_classificacao": (
                    p.data_classificacao.isoformat() if p.data_classificacao else None
                ),
            }
            for p in items
        ],
    }


# ─── Quick PDF (atalho de teste: cria lote + sobe PDF num shot) ──────


@router.post("/lotes/quick-pdf", status_code=status.HTTP_201_CREATED)
def quick_pdf(
    files: list[UploadFile] = File(
        ...,
        description=(
            "1 ou mais PDFs de processo (multipart com multiplos `files`). "
            "Cada PDF vira 1 processo no mesmo lote criado."
        ),
    ),
    nome: Optional[str] = Form(default=None),
    cliente_nome: Optional[str] = Form(default=None),
    cnj_hint: Optional[str] = Form(default=None),
    produto: Optional[str] = Form(default=None),
    observacao: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Atalho pra testar 1 ou MAIS PDFs num shot: cria lote auto + sobe todos.

    Diferente de POST /lotes (xlsx) e /lotes/from-prazos-iniciais — esse
    aqui e' pra teste rapido: operador sobe N PDFs e o sistema cria
    UM lote com nome auto-gerado ("Teste avulso — DD/MM HH:MM" se nao
    informar) contendo um processo por PDF.

    Tolerante a falha: se um PDF nao for valido (vazio, sem magic bytes
    ou maior que o limite), aquele e' marcado como ERRO_CAPTURA e os outros seguem.
    Se TODOS falharem, o lote e' deletado e a request retorna 400.

    Depois operador classifica via UI (botao ✨ no historico) ou worker.

    Returns:
        { lote: {...}, processos: [{...}, ...] }  — 1 entrada por PDF.
    """
    from datetime import datetime as _dt

    from app.core.config import settings as _s
    from app.models.classificador import (
        LOTE_STATUS_RASCUNHO,
        ClassificadorLote,
    )

    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    # Le todos os bytes upfront (cap por arquivo, sem cap total — operador
    # decide volume; UI mostra tamanho total agregado pra ele).
    pdfs: list[tuple[str, bytes, Optional[str]]] = []  # (filename, bytes, error)
    for f in files:
        content = f.file.read()
        if not content:
            pdfs.append((f.filename or "vazio.pdf", b"", "Arquivo vazio."))
            continue
        if len(content) > _s.prazos_iniciais_max_pdf_bytes:
            pdfs.append((
                f.filename or "?.pdf", b"",
                f"Arquivo > {_s.prazos_iniciais_max_pdf_mb}MB.",
            ))
            continue
        pdfs.append((f.filename or "?.pdf", content, None))

    # Nome auto-gerado se nao informar
    nome_final = (nome or "").strip() or (
        f"Teste avulso — {_dt.now().strftime('%d/%m %H:%M')}"
    )
    descricao = (
        "Teste avulso de 1 PDF"
        if len(files) == 1
        else f"Teste avulso de {len(files)} PDFs"
    )

    # 1) Cria lote (guard amplo — bug aqui antes ficava como 500 cru sem stack pro operador)
    try:
        lote = ClassificadorLote(
            nome=nome_final,
            cliente_nome=(cliente_nome or "").strip() or None,
            descricao=descricao,
            status=LOTE_STATUS_RASCUNHO,
            source_summary={},
            snapshot_at=_dt.utcnow(),
            created_by_user_id=current_user.id if current_user else None,
        )
        db.add(lote)
        db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao criar lote no quick-pdf")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao criar lote: {type(exc).__name__}: {exc}",
        )

    # 2) Processa cada PDF — tolerante a falha
    processos_out: list[dict] = []
    sucessos = 0

    for filename, content, pre_error in pdfs:
        if pre_error:
            # PDF nao chegou nem a passar pra ingest_pdf (vazio / muito grande)
            processos_out.append({
                "filename": filename,
                "ok": False,
                "error_message": pre_error,
                "processo": None,
            })
            continue

        try:
            proc = ingest_pdf(
                db,
                lote_id=lote.id,
                pdf_bytes=content,
                pdf_filename=filename,
                source=SOURCE_PDF_UPLOAD,
                cnj_hint=cnj_hint,
                produto=produto,
                metadata={"observacao_operador": observacao} if observacao else None,
                created_by_user_id=current_user.id if current_user else None,
            )
        except PdfValidationError as exc:
            processos_out.append({
                "filename": filename, "ok": False,
                "error_message": str(exc), "processo": None,
            })
            continue
        except PdfIntakeError as exc:
            processos_out.append({
                "filename": filename, "ok": False,
                "error_message": str(exc), "processo": None,
            })
            continue
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha no quick-pdf pra %s", filename)
            processos_out.append({
                "filename": filename, "ok": False,
                "error_message": f"{type(exc).__name__}: {exc}",
                "processo": None,
            })
            continue

        sucessos += 1
        processos_out.append({
            "filename": filename,
            "ok": True,
            "error_message": None,
            "processo": {
                "id": proc.id,
                "lote_id": proc.lote_id,
                "cnj_number": proc.cnj_number,
                "source": proc.source,
                "pdf_filename": proc.pdf_filename_original,
                "pdf_sha256": proc.pdf_sha256,
                "pdf_bytes": proc.pdf_bytes,
                "extractor_used": proc.extractor_used,
                "extraction_confidence": proc.extraction_confidence,
                "pdf_extraction_failed": proc.pdf_extraction_failed,
                "status": proc.status,
                "error_message": proc.error_message,
                "capa_json_keys": (
                    list(proc.capa_json.keys())
                    if isinstance(proc.capa_json, dict) else None
                ),
                "integra_json_keys": (
                    list(proc.integra_json.keys())
                    if isinstance(proc.integra_json, dict) else None
                ),
            },
        })

    # Se TODOS os PDFs falharam, derruba o lote (nao deixa lote vazio)
    if sucessos == 0:
        db.delete(lote)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=(
                f"Nenhum PDF pode ser processado ({len(processos_out)} tentativas). "
                f"Verifique se os arquivos sao PDFs validos e <= {_s.prazos_iniciais_max_pdf_mb}MB."
            ),
        )

    db.refresh(lote)
    return {
        "lote": _serialize_lote(lote),
        "processos": processos_out,
        "summary": {
            "total": len(processos_out),
            "ok": sucessos,
            "failed": len(processos_out) - sucessos,
        },
    }


# ─── Upload de PDF por processo (Fase 3 round 1) ─────────────────────


@router.post(
    "/lotes/{lote_id}/processos/upload-pdf",
    status_code=status.HTTP_201_CREATED,
)
def upload_pdf_to_lote(
    lote_id: int,
    file: UploadFile = File(..., description="PDF do processo completo"),
    cnj_hint: Optional[str] = Form(default=None),
    external_id: Optional[str] = Form(default=None),
    produto: Optional[str] = Form(default=None),
    observacao: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Sobe 1 PDF de processo pra um lote — roda extracao mecanica do PI.

    Caminho de teste manual (operador via UI). O adapter do robo de
    entrega (futura Fase) vai chamar a mesma funcao internamente,
    fora do HTTP.

    Form fields:
    - `file` (obrig.): PDF (<= settings.prazos_iniciais_max_pdf_mb, default 200MB)
    - `cnj_hint` (opc.): CNJ que o cliente afirma ser do processo. Usado
      como fallback se o extractor mecanico nao detectar.
    - `external_id` (opc.): id externo (cliente/robo)
    - `produto` (opc.): produto (Cartao, Cheque Especial, etc.)
    - `observacao` (opc.): texto livre (vai pra metadata_json)

    Pipeline:
    1. Valida PDF (magic bytes + tamanho max)
    2. Salva em volume (sha256-named)
    3. Roda pdf_extractor.extract() do PI (mecanico, sem IA)
    4. Cria ClassificadorProcesso com capa_json + integra_json
    5. Status = PRONTO_PARA_CLASSIFICAR (ou ERRO_CAPTURA se PDF sem texto)

    A classificacao IA acontece depois via POST /lotes/{id}/classify.
    """
    content = file.file.read()
    metadata = {"observacao_operador": observacao} if observacao else None

    try:
        proc = ingest_pdf(
            db,
            lote_id=lote_id,
            pdf_bytes=content,
            pdf_filename=file.filename or "upload.pdf",
            source=SOURCE_PDF_UPLOAD,
            cnj_hint=cnj_hint,
            external_id=external_id,
            produto=produto,
            metadata=metadata,
            created_by_user_id=current_user.id if current_user else None,
        )
    except PdfValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PdfIntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao subir PDF pro lote #%s", lote_id)
        raise HTTPException(
            status_code=500,
            detail=f"Erro inesperado: {type(exc).__name__}: {exc}",
        )

    return {
        "processo": {
            "id": proc.id,
            "lote_id": proc.lote_id,
            "cnj_number": proc.cnj_number,
            "source": proc.source,
            "pdf_filename": proc.pdf_filename_original,
            "pdf_sha256": proc.pdf_sha256,
            "pdf_bytes": proc.pdf_bytes,
            "extractor_used": proc.extractor_used,
            "extraction_confidence": proc.extraction_confidence,
            "pdf_extraction_failed": proc.pdf_extraction_failed,
            "status": proc.status,
            "error_message": proc.error_message,
            "capa_json_keys": (
                list(proc.capa_json.keys()) if isinstance(proc.capa_json, dict) else None
            ),
            "integra_json_keys": (
                list(proc.integra_json.keys())
                if isinstance(proc.integra_json, dict)
                else None
            ),
        },
    }


# ─── Stubs Fase 3 round 2 / Fase 4 ───────────────────────────────────


@router.post("/lotes/{lote_id}/recapture-from-pi")
def recapture_lote_from_pi(
    lote_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Re-popula capa_json + integra_json dos processos do lote a partir dos
    intakes do PI (source_intake_id). Util pra lotes antigos criados antes
    do fix que ja vinham com 0/717 capturados.

    Pra cada ClassificadorProcesso do lote com source=PRAZOS_INICIAIS:
    - Busca PrazoInicialIntake pelo source_intake_id
    - Copia capa_json + integra_json
    - Marca status=PRONTO_PARA_CLASSIFICAR se tiver dados

    Recalcula total_processos_capturados do lote.
    """
    from app.models.classificador import (
        PROC_STATUS_PENDENTE,
        PROC_STATUS_READY,
        SOURCE_PRAZOS_INICIAIS,
    )
    from app.models.prazo_inicial import PrazoInicialIntake

    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    procs = (
        db.query(ClassificadorProcesso)
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.source == SOURCE_PRAZOS_INICIAIS)
        .filter(ClassificadorProcesso.source_intake_id.isnot(None))
        .all()
    )
    if not procs:
        raise HTTPException(
            status_code=400,
            detail=f"Lote #{lote_id} nao tem processos vindos de Prazos Iniciais.",
        )

    intake_ids = [p.source_intake_id for p in procs]
    intakes = (
        db.query(PrazoInicialIntake)
        .filter(PrazoInicialIntake.id.in_(intake_ids))
        .all()
    )
    intake_by_id = {i.id: i for i in intakes}

    atualizados = 0
    capturados = 0
    nao_encontrados = 0
    for p in procs:
        intake = intake_by_id.get(p.source_intake_id)
        if not intake:
            nao_encontrados += 1
            continue
        has_data = bool(intake.capa_json or intake.integra_json)
        p.capa_json = intake.capa_json or {}
        p.integra_json = intake.integra_json or {}
        p.natureza_processo = getattr(intake, "natureza_processo", None)
        p.produto = getattr(intake, "produto", None)
        # So' marca PRONTO se tem dados E ainda nao foi classificado
        if has_data and p.status == PROC_STATUS_PENDENTE:
            p.status = PROC_STATUS_READY
            capturados += 1
        atualizados += 1

    # Recalcula capturados no lote (todos com status >= READY)
    from sqlalchemy import func
    total_cap = (
        db.query(func.count(ClassificadorProcesso.id))
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.status.in_({
            PROC_STATUS_READY,
            "CLASSIFICADO",
            "ERRO_CLASSIFICACAO",
        }))
        .scalar()
    ) or 0
    lote.total_processos_capturados = total_cap

    db.commit()
    logger.info(
        "Classificador: lote #%s recapture-from-pi (%d atualizados, %d novos capturados, %d nao_encontrados)",
        lote_id, atualizados, capturados, nao_encontrados,
    )

    return {
        "lote_id": lote_id,
        "atualizados": atualizados,
        "novos_capturados": capturados,
        "nao_encontrados": nao_encontrados,
        "total_capturados_no_lote": total_cap,
    }


@router.post(
    "/lotes/{lote_id}/capture-l1",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
def capture_l1(lote_id: int):
    """[Fase 2c] Dispara refresh L1 async. Stub."""
    raise HTTPException(
        status_code=501,
        detail="Em construcao — Fase 2c do Classificador (refresh L1 async).",
    )


@router.post("/lotes/{lote_id}/classify", status_code=status.HTTP_202_ACCEPTED)
async def classify_lote(
    lote_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Dispara classificacao Sonnet (Batches API) pros processos PRONTO_PARA_CLASSIFICAR do lote.

    Retorna 202 + batch_id. Status do batch e' atualizado pelo
    `classificador_poll_worker` (APScheduler) — polling a cada 30s.
    """
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    runner = ClassificadorBatchClassifier(db)
    processos = runner.collect_pending_processos(lote_id=lote_id)
    if not processos:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Nenhum processo em PRONTO_PARA_CLASSIFICAR no lote #{lote_id}. "
                "Suba os PDFs antes de classificar."
            ),
        )

    try:
        batch = await runner.submit_batch(
            lote_id=lote_id,
            processos=processos,
            requested_by_email=getattr(current_user, "email", None),
            requested_by_user_id=current_user.id if current_user else None,
        )
    except Exception as exc:
        logger.exception("Falha ao submeter batch lote=%s", lote_id)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao submeter batch: {type(exc).__name__}: {exc}",
        )

    return {
        "batch_id": batch.id,
        "anthropic_batch_id": batch.anthropic_batch_id,
        "anthropic_status": batch.anthropic_status,
        "status": batch.status,
        "total_records": batch.total_records,
        "model_used": batch.model_used,
        "submitted_at": batch.submitted_at.isoformat() if batch.submitted_at else None,
    }


@router.get("/lotes/{lote_id}/batches")
def list_batches(lote_id: int, db: Session = Depends(get_db)):
    """Lista batches Anthropic do lote (mais recente primeiro)."""
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    items = (
        db.query(ClassificadorBatch)
        .filter(ClassificadorBatch.lote_id == lote_id)
        .order_by(ClassificadorBatch.created_at.desc())
        .all()
    )
    return {
        "total": len(items),
        "items": [_serialize_batch(b) for b in items],
    }


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    """Detalhe + contadores de 1 batch Anthropic."""
    b = (
        db.query(ClassificadorBatch)
        .filter(ClassificadorBatch.id == batch_id)
        .first()
    )
    if b is None:
        raise HTTPException(status_code=404, detail=f"Batch #{batch_id} nao encontrado.")
    return _serialize_batch(b)


@router.post("/batches/{batch_id}/refresh-status")
async def refresh_batch_status_endpoint(batch_id: int, db: Session = Depends(get_db)):
    """Forca polling de 1 batch (manual — worker faz periodicamente)."""
    b = (
        db.query(ClassificadorBatch)
        .filter(ClassificadorBatch.id == batch_id)
        .first()
    )
    if b is None:
        raise HTTPException(status_code=404, detail=f"Batch #{batch_id} nao encontrado.")

    runner = ClassificadorBatchClassifier(db)
    try:
        await runner.refresh_batch_status(b)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao atualizar batch: {type(exc).__name__}: {exc}",
        )
    return _serialize_batch(b)


@router.post("/batches/{batch_id}/apply")
async def apply_batch_endpoint(batch_id: int, db: Session = Depends(get_db)):
    """Aplica resultados de batch PRONTO (manual — worker faz periodicamente)."""
    b = (
        db.query(ClassificadorBatch)
        .filter(ClassificadorBatch.id == batch_id)
        .first()
    )
    if b is None:
        raise HTTPException(status_code=404, detail=f"Batch #{batch_id} nao encontrado.")

    if b.status not in (BATCH_STATUS_READY, BATCH_STATUS_APPLIED):
        raise HTTPException(
            status_code=409,
            detail=f"Batch #{batch_id} nao esta PRONTO (status={b.status}).",
        )

    runner = ClassificadorBatchClassifier(db)
    try:
        result = await runner.apply_batch_results(b)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao aplicar batch: {type(exc).__name__}: {exc}",
        )
    return {"batch": _serialize_batch(b), "result": result}


def _serialize_batch(b: ClassificadorBatch) -> dict:
    return {
        "id": b.id,
        "lote_id": b.lote_id,
        "anthropic_batch_id": b.anthropic_batch_id,
        "anthropic_status": b.anthropic_status,
        "status": b.status,
        "total_records": b.total_records,
        "succeeded_count": b.succeeded_count,
        "errored_count": b.errored_count,
        "expired_count": b.expired_count,
        "canceled_count": b.canceled_count,
        "model_used": b.model_used,
        "results_url": b.results_url,
        "error_message": b.error_message,
        "requested_by_email": b.requested_by_email,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "submitted_at": b.submitted_at.isoformat() if b.submitted_at else None,
        "ended_at": b.ended_at.isoformat() if b.ended_at else None,
        "applied_at": b.applied_at.isoformat() if b.applied_at else None,
    }


class RelatorioCreatePayload(BaseModel):
    formato: str = Field(default="XLSX", description="XLSX (Fase 4 Round 1) ou PDF (Round 2)")


@router.post(
    "/lotes/{lote_id}/relatorios",
    status_code=status.HTTP_201_CREATED,
)
def create_relatorio(
    lote_id: int,
    payload: RelatorioCreatePayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Gera relatorio XLSX (sincrono) ou PDF (Round 2 — ainda stub).

    Fluxo:
    1. Valida lote
    2. Monta payload via report_data.build_report_data
    3. Gera xlsx em memoria (openpyxl)
    4. Salva no volume via report_storage
    5. Cria registro em classificador_relatorio (status=PRONTO)

    XLSX <5s pra carteira <10k processos. Acima disso, mover pra async
    (worker APScheduler). Atualmente sincrono.
    """
    from datetime import datetime as _dt
    from app.models.classificador import (
        REL_FORMAT_PDF,
        REL_FORMAT_XLSX,
        REL_STATUS_FALHOU,
        REL_STATUS_PRONTO,
        REL_STATUS_PROCESSANDO,
    )

    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    formato = payload.formato.upper().strip()
    if formato not in (REL_FORMAT_XLSX, REL_FORMAT_PDF):
        raise HTTPException(
            status_code=400,
            detail=f"Formato invalido: {formato!r}. Use XLSX ou PDF.",
        )

    # 1) Cria registro em PROCESSANDO
    now = _dt.utcnow()
    rel = ClassificadorRelatorio(
        lote_id=lote_id,
        formato=formato,
        status=REL_STATUS_PROCESSANDO,
        requested_by_user_id=current_user.id if current_user else None,
        requested_at=now,
        started_at=now,
    )
    db.add(rel)
    db.flush()

    try:
        # 2) Monta payload agregado
        data = build_report_data(db, lote_id)
        # 3) Gera arquivo conforme formato
        if formato == REL_FORMAT_XLSX:
            file_bytes = generate_xlsx_report(data)
            ext = "xlsx"
        else:
            # REL_FORMAT_PDF
            file_bytes = generate_pdf_report(data)
            ext = "pdf"
        # 4) Salva no volume
        stored = save_report(file_bytes, extension=ext)
        # 5) Persiste
        rel.status = REL_STATUS_PRONTO
        rel.file_path = stored.relative_path
        rel.file_bytes = stored.size_bytes
        rel.file_sha256 = stored.sha256
        rel.finished_at = _dt.utcnow()
        rel.params_json = {
            "totals": data.get("kpis"),
            "qtd_processos": data["kpis"].get("total_processos"),
        }
        db.commit()
        db.refresh(rel)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Classificador.report: falha ao gerar %s lote=%s", formato, lote_id)
        rel.status = REL_STATUS_FALHOU
        rel.error_message = f"{type(exc).__name__}: {exc}"
        rel.finished_at = _dt.utcnow()
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar relatorio: {type(exc).__name__}: {exc}",
        )

    return {
        "id": rel.id,
        "lote_id": rel.lote_id,
        "formato": rel.formato,
        "status": rel.status,
        "file_bytes": rel.file_bytes,
        "file_sha256": rel.file_sha256,
        "requested_at": rel.requested_at.isoformat() if rel.requested_at else None,
        "started_at": rel.started_at.isoformat() if rel.started_at else None,
        "finished_at": rel.finished_at.isoformat() if rel.finished_at else None,
    }


@router.get("/lotes/{lote_id}/relatorios")
def list_relatorios(lote_id: int, db: Session = Depends(get_db)):
    """Lista relatorios ja gerados pra esse lote."""
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote #{lote_id} nao encontrado.")

    items = (
        db.query(ClassificadorRelatorio)
        .filter(ClassificadorRelatorio.lote_id == lote_id)
        .order_by(ClassificadorRelatorio.requested_at.desc())
        .all()
    )
    return {
        "total": len(items),
        "items": [
            {
                "id": r.id,
                "formato": r.formato,
                "status": r.status,
                "file_bytes": r.file_bytes,
                "error_message": r.error_message,
                "requested_at": r.requested_at.isoformat() if r.requested_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in items
        ],
    }


@router.get("/lotes/{lote_id}/relatorios/{relatorio_id}/download")
def download_relatorio(
    lote_id: int,
    relatorio_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """Download do arquivo do relatorio (FileResponse com filename amigavel)."""
    from fastapi.responses import FileResponse
    from app.models.classificador import REL_FORMAT_XLSX, REL_STATUS_PRONTO

    rel = (
        db.query(ClassificadorRelatorio)
        .filter(ClassificadorRelatorio.id == relatorio_id)
        .filter(ClassificadorRelatorio.lote_id == lote_id)
        .first()
    )
    if rel is None:
        raise HTTPException(
            status_code=404,
            detail=f"Relatorio #{relatorio_id} nao encontrado no lote #{lote_id}.",
        )
    if rel.status != REL_STATUS_PRONTO or not rel.file_path:
        raise HTTPException(
            status_code=409,
            detail=f"Relatorio #{relatorio_id} nao esta PRONTO (status={rel.status}).",
        )

    try:
        abs_path = resolve_report_path(rel.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not abs_path.exists():
        raise HTTPException(
            status_code=410,
            detail=f"Arquivo do relatorio #{relatorio_id} nao encontrado no volume.",
        )

    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    nome_lote_safe = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (lote.nome if lote else f"lote-{lote_id}")
    )[:60]

    if rel.formato == REL_FORMAT_XLSX:
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"classificador-{nome_lote_safe}-{rel.id}.xlsx"
    else:
        media_type = "application/pdf"
        filename = f"classificador-{nome_lote_safe}-{rel.id}.pdf"

    return FileResponse(path=abs_path, media_type=media_type, filename=filename)
