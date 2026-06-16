"""Endpoints do módulo Citações BM (monitoramento de citação via DataJud).

Montado sob /api/v1/publications/citacoes-bm (dentro de Tratamento de
Publicações). JWT + permissão "publications" como o resto do módulo.
"""

import logging
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import auth
from app.core.dependencies import get_db
from app.models.citacoes_bm import (
    STATUS_CITADO,
    STATUS_NAO_CITADO,
    STATUS_PENDENTE,
)
from app.models.legal_one import LegalOneUser
from app.services.citacoes_bm.service import CitacoesBMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/citacoes-bm")


def _get_service(db: Session = Depends(get_db)) -> CitacoesBMService:
    return CitacoesBMService(db=db)


# ── Schemas ───────────────────────────────────────────────────────────
class IngestListRequest(BaseModel):
    # Aceita lista estruturada OU um blob de texto colado pelo operador.
    cnjs: Optional[list[str]] = None
    text: Optional[str] = None


class IngestL1Request(BaseModel):
    data_corte: Optional[str] = None  # ISO "YYYY-MM-DD"; default = hoje


class ScanRequest(BaseModel):
    limit: Optional[int] = None


class CitacaoPatchRequest(BaseModel):
    status: str  # PENDENTE | CITADO | NAO_CITADO
    observacao: Optional[str] = None


def _split_text_to_cnjs(text: str) -> list[str]:
    import re

    # Quebra por linha, vírgula, ponto-e-vírgula ou espaço.
    return [t for t in re.split(r"[\s,;]+", text or "") if t.strip()]


# ── Leitura ───────────────────────────────────────────────────────────
@router.get("/summary")
def get_summary(
    service: CitacoesBMService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    return service.get_summary()


@router.get("")
@router.get("/")
def list_processos(
    status: Optional[str] = Query(default=None),
    origem: Optional[str] = Query(default=None),
    tribunal_alias: Optional[str] = Query(default=None),
    uf: Optional[str] = Query(default=None),
    apenas_com_novos: bool = Query(default=False),
    arquivados: str = Query(default="ativos"),  # ativos | arquivados | todos
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: CitacoesBMService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    return service.list_processos(
        status=status,
        origem=origem,
        tribunal_alias=tribunal_alias,
        uf=uf,
        apenas_com_novos=apenas_com_novos,
        arquivados=arquivados,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/{processo_id}")
def get_processo(
    processo_id: int,
    service: CitacoesBMService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    detail = service.get_processo_detail(processo_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Processo não encontrado.")
    return detail


# ── Ingestão ──────────────────────────────────────────────────────────
@router.post("/ingest/list")
def ingest_list(
    payload: IngestListRequest,
    service: CitacoesBMService = Depends(_get_service),
    current_user: LegalOneUser = Depends(auth.require_permission("publications")),
):
    cnjs: list[str] = []
    if payload.cnjs:
        cnjs.extend(payload.cnjs)
    if payload.text:
        cnjs.extend(_split_text_to_cnjs(payload.text))
    if not cnjs:
        raise HTTPException(
            status_code=400, detail="Envie 'cnjs' ou 'text' com ao menos um CNJ."
        )
    return service.ingest_lista(cnjs, created_by_email=current_user.email)


@router.post("/ingest/l1")
def ingest_l1(
    payload: IngestL1Request,
    service: CitacoesBMService = Depends(_get_service),
    current_user: LegalOneUser = Depends(auth.require_permission("publications")),
):
    return service.ingest_l1_auto(
        data_corte=payload.data_corte, created_by_email=current_user.email
    )


# ── Varredura ─────────────────────────────────────────────────────────
def _run_scan_all_bg(limit: Optional[int]) -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        res = CitacoesBMService(db=db).scan_all(limit=limit)
        logger.info("Citações BM: scan manual concluído — %s", res)
    except Exception:
        logger.exception("Citações BM: erro no scan manual em background.")
    finally:
        db.close()


@router.post("/scan")
def scan_all(
    payload: ScanRequest,
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    # Varredura geral pode demorar (N processos × rede); roda em background
    # pra não estourar timeout de HTTP. Acompanhe pelos last_scan_at na lista.
    thread = threading.Thread(
        target=_run_scan_all_bg, args=(payload.limit,), daemon=True
    )
    thread.start()
    return {"started": True}


@router.post("/{processo_id}/scan")
def scan_one(
    processo_id: int,
    service: CitacoesBMService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    from app.models.citacoes_bm import CitacaoBMProcesso

    proc = (
        service.db.query(CitacaoBMProcesso)
        .filter(CitacaoBMProcesso.id == processo_id)
        .first()
    )
    if not proc:
        raise HTTPException(status_code=404, detail="Processo não encontrado.")
    return service.scan_processo(proc)


# ── Ações do operador ─────────────────────────────────────────────────
@router.patch("/{processo_id}/citacao")
def patch_citacao(
    processo_id: int,
    payload: CitacaoPatchRequest,
    service: CitacoesBMService = Depends(_get_service),
    current_user: LegalOneUser = Depends(auth.require_permission("publications")),
):
    if payload.status not in {STATUS_PENDENTE, STATUS_CITADO, STATUS_NAO_CITADO}:
        raise HTTPException(status_code=400, detail="Status inválido.")
    proc = service.marcar_citacao(
        processo_id=processo_id,
        status=payload.status,
        user_id=current_user.id,
        user_nome=current_user.name,
        observacao=payload.observacao,
    )
    if not proc:
        raise HTTPException(status_code=404, detail="Processo não encontrado.")
    return service._processo_to_dict(proc)


@router.post("/{processo_id}/mark-read")
def mark_read(
    processo_id: int,
    service: CitacoesBMService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    count = service.marcar_lidos(processo_id)
    return {"marcados": count}
