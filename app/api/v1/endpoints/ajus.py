"""
Endpoints do módulo AJUS — catálogo de códigos de andamento + fila.

Auth: JWT obrigatório, permissão `prazos_iniciais` (mesmo escopo do
intake — quem trata prazos é quem decide quais andamentos vão pra AJUS).
Operações de catálogo (CRUD de cod_andamento) também respeitam a
permissão; operações destrutivas (delete) podem ser restritas a admin
no futuro.
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.ajus import (
    AJUS_QUEUE_PENDENTE,
    AJUS_QUEUE_STATUSES,
    AjusAndamentoQueue,
    AjusCodAndamento,
)
from app.models.legal_one import LegalOneUser
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
