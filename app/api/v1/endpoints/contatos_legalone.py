"""Endpoints do modulo Atualizacao de Contatos LegalOne.

Enriquece contatos ja' existentes no Legal One (achados por CPF/CNPJ) com
telefones/e-mail/endereco, a partir de um CSV Dossie.

- POST   /contatos-legalone/preview         : parseia o CSV e devolve resumo (sem gravar)
- POST   /contatos-legalone/batches         : cria o lote (dry_run por padrao)
- GET    /contatos-legalone/batches         : lista paginada
- GET    /contatos-legalone/batches/{id}    : detalhe
- GET    /contatos-legalone/batches/{id}/status : polling barato (barra de progresso)
- GET    /contatos-legalone/batches/{id}/items  : itens paginados
- POST   /contatos-legalone/batches/{id}/retry-failed
- POST   /contatos-legalone/batches/{id}/cancel
- DELETE /contatos-legalone/batches/{id}

Auth: JWT (router em main.py com protected_dependencies) + permissao
`schedule_batch` (gate do grupo LegalOne). O enriquecimento roda no worker
(app/services/contatos_legalone/enrich_worker.py). O CSV NAO e' persistido
(PII/LGPD) — so' parseado.
"""

from __future__ import annotations

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
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.contato_update import (
    ContatoAtualizacaoBatch,
    ContatoAtualizacaoItem,
)
from app.models.legal_one import LegalOneUser
from app.services.contatos_legalone import batch_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contatos-legalone", tags=["Contatos LegalOne"])

# Limite defensivo de tamanho do CSV (1.212 contatos cabem em << 5 MB).
MAX_CSV_BYTES = 20 * 1024 * 1024


# ─── Helpers ─────────────────────────────────────────────────────────────


def _get_batch_or_404(db: Session, batch_id: int) -> ContatoAtualizacaoBatch:
    batch = db.get(ContatoAtualizacaoBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Lote #{batch_id} nao encontrado.")
    return batch


async def _read_csv(file: UploadFile) -> bytes:
    """Le' o upload validando extensao .csv e tamanho."""
    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(
            status_code=422,
            detail="Envie um arquivo .csv (Dossie com CPF/CNPJ).",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Arquivo vazio.")
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede {MAX_CSV_BYTES // (1024 * 1024)} MB.",
        )
    return content


# ─── Modelo (template CSV) ────────────────────────────────────────────────

# Colunas reconhecidas pelo parser (csv_parser). Obrigatoria: CPF_CNPJ. TODAS
# as demais sao opcionais (permite atualizacoes parciais — ex.: so' NOME, ou
# so' EMAIL). Use o literal NULL (ou deixe vazio) quando nao houver.
# Delimitador ';' (padrao BR); UTF-8 com BOM (Excel/pt-BR).
TEMPLATE_HEADER = (
    "CPF_CNPJ;NOME;DDD;TELEFONE;DDD2;TELEFONE2;DDD3;TELEFONE3;EMAIL;"
    "LOGRADOURO;NUMERO;COMPLEMENTO;BAIRRO;CIDADE;UF;CEP;NOME_ABREVIADO"
)
# Linha de exemplo bem estruturada: o CPF_CNPJ comeca com '#', entao o parser
# IGNORA esta linha (nao vira contato). Serve so' de referencia pro operador.
TEMPLATE_EXEMPLOS = [
    "#000.000.000-00;Maria de Souza (linha de exemplo - sera ignorada);"
    "92;992022665;NULL;NULL;NULL;NULL;maria@exemplo.com;"
    "TV DUTRA;1840;APT 101;NOVA ALTAMIRA;ALTAMIRA;PA;68371550;COBRANCA JUN/2026",
]


@router.get("/template")
def download_template(
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Baixa o modelo .csv esperado (cabecalho + 2 linhas de exemplo)."""
    # BOM (U+FEFF) ajuda o Excel pt-BR a abrir UTF-8 com acentos corretos.
    body = "﻿" + "\r\n".join([TEMPLATE_HEADER, *TEMPLATE_EXEMPLOS]) + "\r\n"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="modelo_atualizacao_contatos.csv"'
        },
    )


# ─── Preview ─────────────────────────────────────────────────────────────


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    _: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Parseia o CSV e devolve resumo + amostra, sem gravar nada."""
    content = await _read_csv(file)
    try:
        return batch_service.preview_csv(content, file.filename or "dossie.csv")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Contatos: falha no preview do CSV.")
        raise HTTPException(
            status_code=422, detail=f"Falha ao ler o CSV: {type(exc).__name__}: {exc}"
        )


# ─── Criacao de lote ──────────────────────────────────────────────────────


@router.post("/batches", status_code=status.HTTP_201_CREATED)
async def create_batch(
    nome: str = Form(..., min_length=1),
    file: UploadFile = File(...),
    description: Optional[str] = Form(default=None),
    dry_run: bool = Form(default=True),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.require_permission("schedule_batch")),
):
    """Cria o lote a partir do CSV. dry_run=True (default) simula sem escrever."""
    content = await _read_csv(file)
    try:
        batch, summary = batch_service.create_batch_from_csv(
            db,
            nome=nome,
            description=description,
            dry_run=dry_run,
            file_bytes=content,
            original_filename=file.filename or "dossie.csv",
            created_by_user_id=current_user.id,
        )
    except batch_service.ContatoValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Planilha com células bloqueantes — corrija antes de enviar.",
                "issues": exc.issues,
                "summary": exc.summary,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Contatos: falha ao criar lote.")
        raise HTTPException(
            status_code=500, detail=f"Erro inesperado: {type(exc).__name__}: {exc}"
        )
    return {"batch": batch_service.serialize_batch(batch), "summary": summary}


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
    q = db.query(ContatoAtualizacaoBatch).order_by(ContatoAtualizacaoBatch.created_at.desc())
    if status_filter:
        q = q.filter(ContatoAtualizacaoBatch.status == status_filter)
    if nome:
        q = q.filter(ContatoAtualizacaoBatch.nome.ilike(f"%{nome}%"))

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
        db.query(ContatoAtualizacaoItem)
        .filter(ContatoAtualizacaoItem.batch_id == batch_id)
        .order_by(ContatoAtualizacaoItem.id.asc())
    )
    if status_filter:
        q = q.filter(ContatoAtualizacaoItem.status == status_filter)

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
    """Re-enfileira itens ERRO + NAO_ENCONTRADO (volta a PENDENTE)."""
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
    """Apaga o lote + itens (cascade)."""
    batch = _get_batch_or_404(db, batch_id)
    batch_service.delete_batch(db, batch)
    return None
