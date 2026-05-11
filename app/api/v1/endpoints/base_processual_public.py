"""Endpoints PUBLICOS (sem JWT) do Base Processual (Chunk 6).

Auth via header `X-Base-Processual-Key`. Sao read-only por design — sem
PATCH/POST. Scopes controlam quais campos sensiveis aparecem na resposta.

Endpoints:
- GET /public/base-processual/health: sem auth (healthcheck simples)
- GET /public/base-processual/processos: lista paginada (scope read_processos+)
- GET /public/base-processual/processos/{cod_ajus}: detalhe
- GET /public/base-processual/processos/by-cnj/{cnj}: lookup por CNJ
- GET /public/base-processual/dashboard/resumo: KPIs publicos (scope read_dashboard+)

Field filtering: keys com scope read_processos NAO veem valores
financeiros. Scope read_valores ou read_all libera os money fields.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func as sa_func, or_ as sa_or, types as sa_types
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.base_processual import (
    BaseProcessualEvento,
    BaseProcessualProcesso,
    BaseProcessualUpload,
    EVENTO_ATUALIZADO,
    EVENTO_ENTROU,
    EVENTO_SAIU,
    PRESENCA_ATIVO,
    PRESENCA_REMOVIDO,
    UPLOAD_STATUS_CONCLUIDO,
)
from app.services.base_processual.api_key_service import (
    BaseProcessualApiKey,
    SCOPE_READ_DASHBOARD,
    SCOPE_READ_PROCESSOS,
    SCOPE_READ_VALORES,
    check_rate_limit,
    find_active_by_plaintext,
    has_scope,
    touch_last_used,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/public/base-processual",
    tags=["Base Processual (Pública)"],
)


# ============================================================================
# Auth dependencies (NAO usa JWT — usa X-Base-Processual-Key)
# ============================================================================


def _require_key(
    x_base_processual_key: Optional[str] = Header(
        None,
        alias="X-Base-Processual-Key",
        description="Chave de API gerada no /admin/base-processual/api-keys",
    ),
    db: Session = Depends(get_db),
) -> BaseProcessualApiKey:
    if not x_base_processual_key or not x_base_processual_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header X-Base-Processual-Key obrigatorio.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    key = find_active_by_plaintext(db, x_base_processual_key.strip())
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave invalida ou revogada.",
        )
    allowed, _remaining = check_rate_limit(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit excedido (max {key.rate_limit_per_min}/min). "
                "Aguarde a janela de 60s e tente novamente."
            ),
        )
    touch_last_used(db, key)
    return key


def _require_scopes(*allowed: str):
    """Dependency factory — exige que a chave tenha algum dos scopes."""

    def _dep(
        key: BaseProcessualApiKey = Depends(_require_key),
    ) -> BaseProcessualApiKey:
        if not has_scope(key, *allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Scope da chave ('{key.scope}') nao tem permissao. "
                    f"Requer um de: {list(allowed)}."
                ),
            )
        return key

    return _dep


# ============================================================================
# Serializacao com scope filtering
# ============================================================================


def _processo_to_public(p: BaseProcessualProcesso, include_valores: bool) -> dict:
    """Serializa processo pra API publica. Money fields so' se include_valores."""
    base = {
        "cod_ajus": p.cod_ajus,
        "numero_processo": p.numero_processo,
        "numero_processo_mascarado": p.numero_processo_mascarado,
        "numero_pasta": p.numero_pasta,
        "acao_principal": p.acao_principal,
        "materia": p.materia,
        "risco_prob_perda": p.risco_prob_perda,
        "tipo_acao": p.tipo_acao,
        "polo": p.polo,
        "natureza": p.natureza,
        "numero_vara": p.numero_vara,
        "foro": p.foro,
        "comarca": p.comarca,
        "uf": p.uf,
        "empresa": p.empresa,
        "grupo_responsavel": p.grupo_responsavel,
        "usuario_responsavel": p.usuario_responsavel,
        "escritorio_responsavel": p.escritorio_responsavel,
        "situacao_processo": p.situacao_processo,
        "justica_honorario": p.justica_honorario,
        "ult_andamento": p.ult_andamento,
        "data_ult_andamento": p.data_ult_andamento.isoformat() if p.data_ult_andamento else None,
        "distribuido_em": p.distribuido_em.isoformat() if p.distribuido_em else None,
        "processo_virtual": p.processo_virtual,
        "presenca_status": p.presenca_status,
        # created_at = quando o processo ENTROU na base pela primeira vez.
        # updated_at = ultima alteracao (inclui reupload, ressurgimento, etc).
        # Polling incremental: filtre por `?created_after=<iso datetime>` pra
        # pegar apenas processos novos desde o ultimo poll.
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if include_valores:
        base.update({
            "valor_causa": float(p.valor_causa) if p.valor_causa is not None else None,
            "valor_prev_acordo": float(p.valor_prev_acordo) if p.valor_prev_acordo is not None else None,
            "valor_acordo": float(p.valor_acordo) if p.valor_acordo is not None else None,
            "valor_discutido": float(p.valor_discutido) if p.valor_discutido is not None else None,
            "valor_exito": float(p.valor_exito) if p.valor_exito is not None else None,
            "valor_condenacao": float(p.valor_condenacao) if p.valor_condenacao is not None else None,
            "valor_contingencia": float(p.valor_contingencia) if p.valor_contingencia is not None else None,
        })
    return base


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/health")
def public_health():
    """Healthcheck publico — nao requer auth. Use pra validar conectividade."""
    return {"status": "ok", "modulo": "base-processual-public"}


@router.get("/processos")
def public_list_processos(
    presenca_status: Optional[str] = Query(None),
    empresa: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    comarca: Optional[str] = Query(None),
    polo: Optional[str] = Query(None),
    situacao_processo: Optional[str] = Query(None),
    materia: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    created_after: Optional[datetime] = Query(
        None,
        description=(
            "ISO datetime — retorna apenas processos cujo `created_at >= valor`. "
            "Use pra polling incremental: passe o timestamp do ultimo poll."
        ),
    ),
    updated_after: Optional[datetime] = Query(
        None,
        description=(
            "ISO datetime — retorna processos com `updated_at >= valor`. "
            "Diferente de created_after: pega novos + alterados (ex.: mudou responsavel)."
        ),
    ),
    sort_by: str = Query(
        default="created_asc",
        description=(
            "Ordenacao. 'created_asc' (default, estavel pra paginacao + polling), "
            "'created_desc', 'updated_desc', 'ult_andamento_desc'."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    key: BaseProcessualApiKey = Depends(
        _require_scopes(
            SCOPE_READ_PROCESSOS, SCOPE_READ_VALORES
        )
    ),
):
    """Lista paginada (cap=200) com filtros principais + filtros temporais.

    **Campos de valor** (`valor_causa`, etc) so' aparecem se a chave tem scope
    `read_valores` ou `read_all`.

    **Polling incremental** (caso de uso: robo externo baixando integra de
    processos novos): use `?created_after=<ultimo_poll>&sort_by=created_asc`.
    A paginacao e' estavel — processos inseridos entre paginas aparecem so'
    nas paginas posteriores.

    Default: presenca_status=ATIVO_NA_BASE, sort=created_asc.
    """
    q = db.query(BaseProcessualProcesso)
    if presenca_status:
        q = q.filter(BaseProcessualProcesso.presenca_status == presenca_status)
    else:
        q = q.filter(BaseProcessualProcesso.presenca_status == PRESENCA_ATIVO)
    if empresa:
        q = q.filter(BaseProcessualProcesso.empresa == empresa)
    if uf:
        q = q.filter(BaseProcessualProcesso.uf == uf.upper())
    if comarca:
        q = q.filter(BaseProcessualProcesso.comarca.ilike(f"%{comarca}%"))
    if polo:
        q = q.filter(BaseProcessualProcesso.polo == polo)
    if situacao_processo:
        q = q.filter(BaseProcessualProcesso.situacao_processo == situacao_processo)
    if materia:
        q = q.filter(BaseProcessualProcesso.materia == materia)
    if created_after is not None:
        q = q.filter(BaseProcessualProcesso.created_at >= created_after)
    if updated_after is not None:
        q = q.filter(BaseProcessualProcesso.updated_at >= updated_after)
    if search:
        s = search.strip()
        if s:
            digits = re.sub(r"[^0-9]", "", s)
            subs = [BaseProcessualProcesso.cod_ajus.ilike(f"%{s}%")]
            if digits and len(digits) >= 5:
                subs.append(BaseProcessualProcesso.numero_processo.ilike(f"%{digits}%"))
            subs.append(BaseProcessualProcesso.numero_pasta.ilike(f"%{s}%"))
            q = q.filter(sa_or(*subs))

    sort_map = {
        "created_asc": BaseProcessualProcesso.created_at.asc(),
        "created_desc": BaseProcessualProcesso.created_at.desc(),
        "updated_desc": BaseProcessualProcesso.updated_at.desc(),
        "ult_andamento_desc": BaseProcessualProcesso.data_ult_andamento.desc().nullslast(),
    }
    q = q.order_by(sort_map.get(sort_by, sort_map["created_asc"]))
    total = q.count()
    items_db = q.limit(limit).offset(offset).all()
    include_valores = has_scope(key, SCOPE_READ_VALORES)
    items = [_processo_to_public(p, include_valores) for p in items_db]
    return {"total": total, "items": items}


@router.get("/processos/by-cnj/{cnj}")
def public_get_by_cnj(
    cnj: str,
    db: Session = Depends(get_db),
    key: BaseProcessualApiKey = Depends(
        _require_scopes(SCOPE_READ_PROCESSOS, SCOPE_READ_VALORES)
    ),
):
    """Lookup por CNJ. Aceita com ou sem mascara — extraido pra digits."""
    digits = re.sub(r"[^0-9]", "", cnj or "")
    if not digits:
        raise HTTPException(
            status_code=400, detail="CNJ vazio ou invalido."
        )
    items = (
        db.query(BaseProcessualProcesso)
        .filter(BaseProcessualProcesso.numero_processo == digits)
        .all()
    )
    if not items:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum processo com numero_processo={digits}.",
        )
    include_valores = has_scope(key, SCOPE_READ_VALORES)
    if len(items) == 1:
        return _processo_to_public(items[0], include_valores)
    # Multi-match (raro — mesmo CNJ em multiplos cod_ajus): retorna lista
    return {
        "total": len(items),
        "items": [_processo_to_public(p, include_valores) for p in items],
    }


@router.get("/processos/{cod_ajus}")
def public_get_processo(
    cod_ajus: str,
    db: Session = Depends(get_db),
    key: BaseProcessualApiKey = Depends(
        _require_scopes(SCOPE_READ_PROCESSOS, SCOPE_READ_VALORES)
    ),
):
    p = (
        db.query(BaseProcessualProcesso)
        .filter(BaseProcessualProcesso.cod_ajus == cod_ajus)
        .first()
    )
    if p is None:
        raise HTTPException(
            status_code=404, detail=f"Processo {cod_ajus} nao encontrado."
        )
    include_valores = has_scope(key, SCOPE_READ_VALORES)
    return _processo_to_public(p, include_valores)


@router.get("/dashboard/resumo")
def public_dashboard_resumo(
    db: Session = Depends(get_db),
    key: BaseProcessualApiKey = Depends(_require_scopes(SCOPE_READ_DASHBOARD)),
):
    """KPIs principais — count by status + last upload."""
    from datetime import datetime, timedelta

    ativos = (
        db.query(sa_func.count(BaseProcessualProcesso.id))
        .filter(BaseProcessualProcesso.presenca_status == PRESENCA_ATIVO)
        .scalar() or 0
    )
    removidos = (
        db.query(sa_func.count(BaseProcessualProcesso.id))
        .filter(BaseProcessualProcesso.presenca_status == PRESENCA_REMOVIDO)
        .scalar() or 0
    )
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    eventos = (
        db.query(BaseProcessualEvento.tipo_evento, sa_func.count())
        .filter(BaseProcessualEvento.created_at >= today_start)
        .filter(BaseProcessualEvento.created_at < tomorrow_start)
        .group_by(BaseProcessualEvento.tipo_evento)
        .all()
    )
    counts = {row[0]: int(row[1]) for row in eventos}
    ultimo_upload = (
        db.query(BaseProcessualUpload)
        .filter(BaseProcessualUpload.status == UPLOAD_STATUS_CONCLUIDO)
        .order_by(BaseProcessualUpload.committed_at.desc().nullslast())
        .first()
    )
    return {
        "total_ativos_na_base": int(ativos),
        "total_removidos_na_base": int(removidos),
        "eventos_hoje": {
            "entraram": counts.get(EVENTO_ENTROU, 0),
            "sairam": counts.get(EVENTO_SAIU, 0),
            "atualizados": counts.get(EVENTO_ATUALIZADO, 0),
        },
        "ultimo_upload_em": (
            ultimo_upload.committed_at.isoformat()
            if ultimo_upload and ultimo_upload.committed_at
            else None
        ),
    }
