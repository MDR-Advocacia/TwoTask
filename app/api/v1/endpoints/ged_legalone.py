"""Endpoints do modulo GED LegalOne — envio em lote de arquivos pro GED do L1.

Dois modos de criacao de lote:
- POST /ged-legalone/batches/single : 1 arquivo -> N CNJs (modo SINGLE_FILE)
- POST /ged-legalone/batches/multi  : N arquivos -> N CNJs (modo MULTI_FILE)

CRUD + acompanhamento:
- GET    /ged-legalone/batches            : lista paginada
- GET    /ged-legalone/batches/{id}       : detalhe
- GET    /ged-legalone/batches/{id}/status: polling barato (barra de progresso)
- GET    /ged-legalone/batches/{id}/items : itens paginados
- POST   /ged-legalone/batches/{id}/retry-failed
- POST   /ged-legalone/batches/{id}/cancel
- DELETE /ged-legalone/batches/{id}
- GET    /ged-legalone/document-types     : catalogo de tipos do GED (dropdown)

Auth: JWT (router em main.py com protected_dependencies) + permissao
`schedule_batch` (gate do grupo LegalOne no sidebar/admin). O upload em si
roda no worker (app/services/ged_legalone/upload_worker.py).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.ged_legalone import GedUploadBatch, GedUploadItem
from app.models.legal_one import LegalOneUser
from app.services.ged_legalone import batch_service, storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ged-legalone", tags=["GED LegalOne"])


# Catalogo de tipos do GED conhecidos (formato "type_N", descoberto em
# 2026-05-04 — ver legal_one_client.upload_document_to_ged). A UI mostra
# isso num dropdown; default = sem tipo.
GED_DOCUMENT_TYPES = [
    {"type_id": None, "label": "Sem tipo (definir no L1 depois)"},
    {"type_id": "type_48", "label": "Documento / Habilitacao"},
    {"type_id": "type_24", "label": "Peca processual / Peticao inicial"},
    {"type_id": "type_17", "label": "Peca processual / Contestacao"},
    {"type_id": "type_5", "label": "Documento / Certidao"},
    {"type_id": "type_45", "label": "Financeiro / Comprovante de Pagamento"},
]
_VALID_TYPE_IDS = {t["type_id"] for t in GED_DOCUMENT_TYPES if t["type_id"]}


# ─── Helpers ─────────────────────────────────────────────────────────────


def _get_batch_or_404(db: Session, batch_id: int) -> GedUploadBatch:
    batch = db.get(GedUploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Lote #{batch_id} nao encontrado.")
    return batch


def _validate_type_id(type_id: Optional[str]) -> Optional[str]:
    clean = (type_id or "").strip() or None
    if clean is not None and clean not in _VALID_TYPE_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"type_id invalido: {clean}. Use um dos tipos do catalogo ou nenhum.",
        )
    return clean


def _validate_one_file(content: bytes, filename: str) -> str:
    """Valida tamanho + extensao de 1 arquivo. Retorna a ext normalizada
    ou levanta HTTPException (413/422)."""
    ext = storage.normalize_ext(filename)
    try:
        storage.validate_file_bytes(content, ext)
    except storage.FileValidationError as exc:
        # tamanho -> 413; extensao/vazio -> 422
        code = 413 if "tamanho maximo" in str(exc) else 422
        raise HTTPException(status_code=code, detail=f"{filename}: {exc}")
    return ext


# ─── Catalogo de tipos ───────────────────────────────────────────────────


@router.get("/document-types")
def list_document_types(
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Catalogo de tipos do GED pro dropdown da UI."""
    return {"items": GED_DOCUMENT_TYPES}


# ─── Criacao de lotes ────────────────────────────────────────────────────


@router.post("/batches/single", status_code=status.HTTP_201_CREATED)
async def create_batch_single(
    nome: str = Form(..., min_length=1),
    cnj_list: str = Form(..., description="CNJs separados por linha, virgula ou ponto-e-virgula."),
    file: UploadFile = File(..., description="Arquivo unico que vai pra todos os CNJs."),
    type_id: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Modo SINGLE_FILE: um arquivo unico enviado pra varios processos."""
    type_clean = _validate_type_id(type_id)
    content = await file.read()
    ext = _validate_one_file(content, file.filename or "arquivo")

    try:
        batch, summary = batch_service.create_batch_single(
            db,
            nome=nome,
            type_id=type_clean,
            description=description,
            cnj_raw=cnj_list,
            file_bytes=content,
            original_filename=file.filename or f"arquivo.{ext}",
            created_by_user_id=current_user.id if current_user else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except storage.FileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("GED LegalOne: falha ao criar lote single.")
        raise HTTPException(status_code=500, detail=f"Erro inesperado: {type(exc).__name__}: {exc}")

    return {"batch": batch_service.serialize_batch(batch), "resolve_summary": summary}


@router.post("/batches/multi", status_code=status.HTTP_201_CREATED)
async def create_batch_multi(
    nome: str = Form(..., min_length=1),
    files: list[UploadFile] = File(..., description="Varios arquivos (CNJ no nome ou via cnj_overrides)."),
    type_id: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    cnj_overrides: Optional[str] = Form(
        default=None,
        description='JSON {nome_do_arquivo: cnj} pra corrigir/atribuir CNJ por arquivo.',
    ),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Modo MULTI_FILE: varios arquivos, cada um mapeado a um CNJ."""
    type_clean = _validate_type_id(type_id)
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    overrides: dict[str, str] = {}
    if cnj_overrides:
        try:
            parsed = json.loads(cnj_overrides)
            if isinstance(parsed, dict):
                overrides = {str(k): str(v) for k, v in parsed.items() if v}
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=422, detail="cnj_overrides nao e' um JSON valido.")

    # Le + valida TODOS os arquivos antes de criar o lote (tudo ou nada).
    file_entries: list[dict] = []
    for upload in files:
        filename = upload.filename or "arquivo"
        content = await upload.read()
        _validate_one_file(content, filename)  # levanta 413/422 se invalido
        file_entries.append({"filename": filename, "bytes": content})

    try:
        batch, summary = batch_service.create_batch_multi(
            db,
            nome=nome,
            type_id=type_clean,
            description=description,
            files=file_entries,
            cnj_overrides=overrides,
            created_by_user_id=current_user.id if current_user else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except storage.FileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("GED LegalOne: falha ao criar lote multi.")
        raise HTTPException(status_code=500, detail=f"Erro inesperado: {type(exc).__name__}: {exc}")

    return {"batch": batch_service.serialize_batch(batch), "resolve_summary": summary}


# ─── Listagem / detalhe / status ─────────────────────────────────────────


@router.get("/batches")
def list_batches(
    status_filter: Optional[str] = Query(None, alias="status"),
    nome: Optional[str] = Query(None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Lista paginada dos lotes — mais recente primeiro."""
    q = db.query(GedUploadBatch).order_by(GedUploadBatch.created_at.desc())
    if status_filter:
        q = q.filter(GedUploadBatch.status == status_filter)
    if nome:
        q = q.filter(GedUploadBatch.nome.ilike(f"%{nome}%"))

    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return {
        "total": total,
        "items": [batch_service.serialize_batch(b) for b in items],
    }


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    batch = _get_batch_or_404(db, batch_id)
    return batch_service.serialize_batch(batch)


@router.get("/batches/{batch_id}/status")
def get_batch_status(
    batch_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Payload barato pro polling da barra de progresso (sem itens)."""
    batch = _get_batch_or_404(db, batch_id)
    return batch_service.status_payload(batch)


@router.get("/batches/{batch_id}/items")
def list_batch_items(
    batch_id: int,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Itens do lote, paginados — pra tabela de acompanhamento."""
    _get_batch_or_404(db, batch_id)
    q = (
        db.query(GedUploadItem)
        .filter(GedUploadItem.batch_id == batch_id)
        .order_by(GedUploadItem.id.asc())
    )
    if status_filter:
        q = q.filter(GedUploadItem.status == status_filter)

    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return {
        "total": total,
        "items": [batch_service.serialize_item(it) for it in items],
    }


# ─── Acoes ───────────────────────────────────────────────────────────────


@router.post("/batches/{batch_id}/retry-failed")
def retry_failed(
    batch_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Re-enfileira itens ERRO + CNJ_NAO_ENCONTRADO (volta a PENDENTE)."""
    batch = _get_batch_or_404(db, batch_id)
    try:
        result = batch_service.retry_failed(db, batch)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"batch": batch_service.serialize_batch(batch), **result}


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Cancela o lote — worker para de pegar os itens pendentes."""
    batch = _get_batch_or_404(db, batch_id)
    batch = batch_service.cancel_batch(db, batch)
    return batch_service.serialize_batch(batch)


@router.delete("/batches/{batch_id}", status_code=204)
def delete_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Apaga o lote + itens (cascade) + arquivos do volume."""
    batch = _get_batch_or_404(db, batch_id)
    batch_service.delete_batch(db, batch)
    return None
