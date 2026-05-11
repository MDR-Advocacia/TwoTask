"""Endpoints internos do modulo Base Processual.

Prefixo final: /api/v1/admin/base-processual.
Auth: admin-only (role=admin no LegalOneUser). Granularidade vira em
fase 2 via flag no User caso necessario.

Chunk 1: upload (dry-run + commit + direto), listagem de uploads, detalhe,
eventos do upload, download do XLSX original.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    BaseProcessualEventoListResponse,
    BaseProcessualEventoOut,
    BaseProcessualUploadListResponse,
    BaseProcessualUploadOut,
    BaseProcessualUploadResult,
)
from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.base_processual import (
    BaseProcessualEvento,
    BaseProcessualUpload,
)
from app.models.legal_one import LegalOneUser
from app.services.base_processual.storage import save_xlsx
from app.services.base_processual.upload_processor import (
    UploadResult,
    commit_dry_run,
    process_upload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/base-processual", tags=["Base Processual"])


# 30 MB — folga 15x sobre planilha real (5.979 linhas ~ 2MB).
MAX_XLSX_BYTES = 30 * 1024 * 1024

_ALLOWED_XLSX_CTYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",  # alguns browsers nao setam content_type
}


def require_admin(
    current: LegalOneUser = Depends(auth_security.get_current_user),
) -> LegalOneUser:
    """v1 e' admin-only. Granularidade vira em fase 2 via flag no User."""
    if getattr(current, "role", "user") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem acessar a Base Processual.",
        )
    return current


def _ensure_xlsx_file(file: UploadFile, content: bytes) -> None:
    if len(content) > MAX_XLSX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede o limite de {MAX_XLSX_BYTES // (1024 * 1024)} MB.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    name = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()
    if not name.endswith(".xlsx") and ctype not in _ALLOWED_XLSX_CTYPES:
        raise HTTPException(
            status_code=400,
            detail="Tipo de arquivo invalido. Envie um .xlsx (Excel).",
        )


def _result_to_schema(result: UploadResult) -> BaseProcessualUploadResult:
    return BaseProcessualUploadResult(
        upload_id=result.upload_id,
        status=result.status,
        summary_novos=result.summary_novos,
        summary_removidos=result.summary_removidos,
        summary_atualizados=result.summary_atualizados,
        summary_inalterados=result.summary_inalterados,
        error_message=result.error_message,
        is_idempotente=result.is_idempotente,
        eventos_preview=result.eventos_preview,
    )


@router.post("/uploads/dry-run", response_model=BaseProcessualUploadResult)
async def upload_dry_run(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Simula o diff sem persistir. Devolve summary + lista compacta de eventos previstos."""
    content = await file.read()
    _ensure_xlsx_file(file, content)
    try:
        storage_path, _sha = save_xlsx(content)
    except OSError as exc:
        logger.exception("Falha ao gravar XLSX em disco")
        raise HTTPException(
            status_code=500, detail=f"Falha ao gravar arquivo: {exc}"
        ) from exc
    result = process_upload(
        db=db,
        filename=file.filename or "uploaded.xlsx",
        content=content,
        uploaded_by_user_id=user.id,
        dry_run=True,
        storage_path=storage_path,
    )
    return _result_to_schema(result)


@router.post(
    "/uploads/{dry_run_id}/commit",
    response_model=BaseProcessualUploadResult,
)
def commit_upload(
    dry_run_id: int,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Confirma um dry-run pendente. Re-le o XLSX do disco e aplica."""
    try:
        result = commit_dry_run(db, dry_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result_to_schema(result)


@router.post("/uploads", response_model=BaseProcessualUploadResult)
async def upload_direct(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Atalho: aplica direto sem passar por dry-run (mais legado/automacao)."""
    content = await file.read()
    _ensure_xlsx_file(file, content)
    try:
        storage_path, _sha = save_xlsx(content)
    except OSError as exc:
        logger.exception("Falha ao gravar XLSX em disco")
        raise HTTPException(
            status_code=500, detail=f"Falha ao gravar arquivo: {exc}"
        ) from exc
    result = process_upload(
        db=db,
        filename=file.filename or "uploaded.xlsx",
        content=content,
        uploaded_by_user_id=user.id,
        dry_run=False,
        storage_path=storage_path,
    )
    return _result_to_schema(result)


@router.get("/uploads", response_model=BaseProcessualUploadListResponse)
def list_uploads(
    status_filter: Optional[str] = Query(None, alias="status"),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    q = db.query(BaseProcessualUpload).order_by(
        BaseProcessualUpload.uploaded_at.desc()
    )
    if status_filter:
        q = q.filter(BaseProcessualUpload.status == status_filter)
    if from_date:
        q = q.filter(BaseProcessualUpload.uploaded_at >= from_date)
    if to_date:
        q = q.filter(BaseProcessualUpload.uploaded_at <= to_date)
    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualUploadListResponse(
        total=total,
        items=[BaseProcessualUploadOut.model_validate(u) for u in items],
    )


@router.get("/uploads/{upload_id}", response_model=BaseProcessualUploadOut)
def get_upload(
    upload_id: int,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    u = (
        db.query(BaseProcessualUpload)
        .filter(BaseProcessualUpload.id == upload_id)
        .first()
    )
    if u is None:
        raise HTTPException(
            status_code=404, detail=f"Upload #{upload_id} nao encontrado."
        )
    return BaseProcessualUploadOut.model_validate(u)


@router.get(
    "/uploads/{upload_id}/eventos",
    response_model=BaseProcessualEventoListResponse,
)
def list_eventos_do_upload(
    upload_id: int,
    tipo_evento: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    q = (
        db.query(BaseProcessualEvento)
        .filter(BaseProcessualEvento.upload_id == upload_id)
        .order_by(BaseProcessualEvento.id.asc())
    )
    if tipo_evento:
        q = q.filter(BaseProcessualEvento.tipo_evento == tipo_evento)
    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualEventoListResponse(
        total=total,
        items=[BaseProcessualEventoOut.model_validate(e) for e in items],
    )


@router.get("/uploads/{upload_id}/download")
def download_xlsx(
    upload_id: int,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    u = (
        db.query(BaseProcessualUpload)
        .filter(BaseProcessualUpload.id == upload_id)
        .first()
    )
    if u is None:
        raise HTTPException(
            status_code=404, detail=f"Upload #{upload_id} nao encontrado."
        )
    if not u.storage_path:
        raise HTTPException(
            status_code=404, detail="Arquivo original nao esta mais em disco."
        )
    return FileResponse(
        path=u.storage_path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        filename=u.filename,
    )


# ============================================================================
# Dashboard (Chunk 2)
# ============================================================================

import os
import re
from datetime import date as date_type, timedelta

from sqlalchemy import func as sa_func, or_ as sa_or, types as sa_types

from app.api.v1.schemas import (
    BaseProcessualInatividadeOut,
    BaseProcessualMovimentacaoDoDiaResponse,
    BaseProcessualMovimentacaoItem,
    BaseProcessualProcessoListResponse,
    BaseProcessualProcessoOut,
    BaseProcessualProcessoPatch,
    BaseProcessualResumoOut,
    BaseProcessualSerieDiariaItem,
    BaseProcessualSerieDiariaResponse,
    BaseProcessualSnapshotListResponse,
    BaseProcessualSnapshotOut,
    BaseProcessualTopResponsavelItem,
    BaseProcessualUfItem,
)
from app.models.base_processual import (
    BaseProcessualProcesso,
    BaseProcessualSnapshot,
    EVENTO_ATUALIZADO,
    EVENTO_ATUALIZADO_MANUAL,
    EVENTO_ENTROU,
    EVENTO_SAIU,
    PRESENCA_ATIVO,
    PRESENCA_REMOVIDO,
    UPLOAD_STATUS_CONCLUIDO,
)
from app.services.base_processual.diff import compute_diff_hash
from app.services.base_processual.upload_processor import _payload_normalized_json


def _today_utc() -> datetime:
    """Inicio do dia UTC atual (00:00:00 UTC)."""
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def _parse_data_query(value: Optional[datetime]) -> datetime:
    """Normaliza o filtro `data` pra inicio do dia (descarta hora)."""
    if value is None:
        return _today_utc()
    return datetime(value.year, value.month, value.day)


@router.get("/dashboard/resumo", response_model=BaseProcessualResumoOut)
def dashboard_resumo(
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """KPIs principais: ativos, eventos do dia, ultimo upload, top responsaveis, UF."""
    today_start = _today_utc()
    tomorrow_start = today_start + timedelta(days=1)

    total_ativos = (
        db.query(sa_func.count(BaseProcessualProcesso.id))
        .filter(BaseProcessualProcesso.presenca_status == PRESENCA_ATIVO)
        .scalar()
        or 0
    )
    total_removidos = (
        db.query(sa_func.count(BaseProcessualProcesso.id))
        .filter(BaseProcessualProcesso.presenca_status == PRESENCA_REMOVIDO)
        .scalar()
        or 0
    )

    # Eventos do dia — NET (estado liquido), nao a soma bruta de eventos.
    # Filtra por presenca atual + DISTINCT pra evitar contar 2x o mesmo processo
    # quando ele teve multiplos ENTROU/SAIU no dia (ex.: ressurgimento).
    def _distinct_processos_com_evento_hoje(tipo: str, presenca: Optional[str]) -> int:
        q = (
            db.query(sa_func.count(sa_func.distinct(BaseProcessualEvento.processo_id)))
            .select_from(BaseProcessualEvento)
            .join(
                BaseProcessualProcesso,
                BaseProcessualEvento.processo_id == BaseProcessualProcesso.id,
            )
            .filter(BaseProcessualEvento.created_at >= today_start)
            .filter(BaseProcessualEvento.created_at < tomorrow_start)
            .filter(BaseProcessualEvento.tipo_evento == tipo)
        )
        if presenca is not None:
            q = q.filter(BaseProcessualProcesso.presenca_status == presenca)
        return int(q.scalar() or 0)

    novos_hoje = _distinct_processos_com_evento_hoje(EVENTO_ENTROU, PRESENCA_ATIVO)
    saidos_hoje = _distinct_processos_com_evento_hoje(EVENTO_SAIU, PRESENCA_REMOVIDO)
    # ATUALIZADO nao tem estado "reverso" — conta todos os distintos
    atualizados_hoje = _distinct_processos_com_evento_hoje(EVENTO_ATUALIZADO, None)

    # ultimo upload (qualquer status — pra UI mostrar inclusive os FALHOU recentes)
    ultimo_upload = (
        db.query(BaseProcessualUpload)
        .order_by(BaseProcessualUpload.uploaded_at.desc())
        .first()
    )

    # top 10 responsaveis por carteira ATIVA
    top_responsaveis_rows = (
        db.query(
            BaseProcessualProcesso.usuario_responsavel,
            sa_func.count().label("total"),
        )
        .filter(BaseProcessualProcesso.presenca_status == PRESENCA_ATIVO)
        .group_by(BaseProcessualProcesso.usuario_responsavel)
        .order_by(sa_func.count().desc())
        .limit(10)
        .all()
    )
    top_responsaveis = [
        BaseProcessualTopResponsavelItem(
            usuario_responsavel=row[0], total=int(row[1])
        )
        for row in top_responsaveis_rows
    ]

    # distribuicao UF (todas as UFs)
    uf_rows = (
        db.query(
            BaseProcessualProcesso.uf,
            sa_func.count().label("total"),
        )
        .filter(BaseProcessualProcesso.presenca_status == PRESENCA_ATIVO)
        .group_by(BaseProcessualProcesso.uf)
        .order_by(sa_func.count().desc())
        .all()
    )
    distribuicao_uf = [
        BaseProcessualUfItem(uf=row[0], total=int(row[1])) for row in uf_rows
    ]

    return BaseProcessualResumoOut(
        total_ativos_na_base=total_ativos,
        total_removidos_na_base=total_removidos,
        novos_hoje=novos_hoje,
        saidos_hoje=saidos_hoje,
        atualizados_hoje=atualizados_hoje,
        ultimo_upload_id=ultimo_upload.id if ultimo_upload else None,
        ultimo_upload_em=ultimo_upload.uploaded_at if ultimo_upload else None,
        ultimo_upload_status=ultimo_upload.status if ultimo_upload else None,
        ultimo_upload_filename=ultimo_upload.filename if ultimo_upload else None,
        top_responsaveis=top_responsaveis,
        distribuicao_uf=distribuicao_uf,
    )


@router.get(
    "/dashboard/serie-diaria",
    response_model=BaseProcessualSerieDiariaResponse,
)
def dashboard_serie_diaria(
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Serie diaria de eventos (ENTROU/SAIU/ATUALIZADO). Default = ultimos 90d."""
    end = _parse_data_query(to_date) + timedelta(days=1)
    if from_date is None:
        start = end - timedelta(days=91)
    else:
        start = _parse_data_query(from_date)

    # Cast created_at pra date (descarta TZ). Agrupa por date + tipo.
    # PG faz a conversao na session TZ — alinhado com o que o operador ve no UI.
    day_col = sa_func.cast(BaseProcessualEvento.created_at, sa_types.Date)
    rows = (
        db.query(
            day_col.label("dia"),
            BaseProcessualEvento.tipo_evento,
            sa_func.count().label("total"),
        )
        .filter(BaseProcessualEvento.created_at >= start)
        .filter(BaseProcessualEvento.created_at < end)
        .group_by("dia", BaseProcessualEvento.tipo_evento)
        .order_by("dia")
        .all()
    )

    # Pivot por date (nao datetime). Evita mismatch de tzinfo.
    by_day: dict[date_type, dict[str, int]] = {}
    for dia, tipo, total in rows:
        if hasattr(dia, "date"):
            d: date_type = dia.date()
        else:
            d = dia
        by_day.setdefault(d, {})[tipo] = int(total)

    # Preencher TODOS os dias do range (zero quando nao tem evento)
    items: list[BaseProcessualSerieDiariaItem] = []
    cur = start.date() if hasattr(start, "date") else start
    end_excl = end.date() if hasattr(end, "date") else end
    while cur < end_excl:
        bucket = by_day.get(cur, {})
        items.append(
            BaseProcessualSerieDiariaItem(
                data=datetime(cur.year, cur.month, cur.day),
                novos=bucket.get(EVENTO_ENTROU, 0),
                removidos=bucket.get(EVENTO_SAIU, 0),
                atualizados=bucket.get(EVENTO_ATUALIZADO, 0),
            )
        )
        cur += timedelta(days=1)

    return BaseProcessualSerieDiariaResponse(
        from_date=start,
        to_date=end - timedelta(days=1),
        items=items,
    )


@router.get(
    "/dashboard/movimentacao-do-dia",
    response_model=BaseProcessualMovimentacaoDoDiaResponse,
)
def dashboard_movimentacao_do_dia(
    data: Optional[datetime] = Query(None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Listas detalhadas das movimentacoes de um dia (default = hoje UTC).

    Retorna entraram/sairam/atualizados (cada um cap=limit) + totais.
    """
    day_start = _parse_data_query(data)
    day_end = day_start + timedelta(days=1)

    base_q = (
        db.query(BaseProcessualEvento)
        .join(
            BaseProcessualProcesso,
            BaseProcessualEvento.processo_id == BaseProcessualProcesso.id,
        )
        .filter(BaseProcessualEvento.created_at >= day_start)
        .filter(BaseProcessualEvento.created_at < day_end)
    )

    # Filtros por estado liquido + dedup por processo (mantem o evento mais recente).
    # Evita ENTROU+SAIU+ENTROU do mesmo cod_ajus virarem 3 linhas confusas no UI.
    _presenca_por_tipo = {
        EVENTO_ENTROU: PRESENCA_ATIVO,
        EVENTO_SAIU: PRESENCA_REMOVIDO,
    }

    def _items_for(tipo: str) -> tuple[int, list[BaseProcessualMovimentacaoItem]]:
        q = base_q.filter(BaseProcessualEvento.tipo_evento == tipo)
        presenca_filter = _presenca_por_tipo.get(tipo)
        if presenca_filter is not None:
            q = q.filter(BaseProcessualProcesso.presenca_status == presenca_filter)
        total = (
            db.query(sa_func.count(sa_func.distinct(BaseProcessualEvento.processo_id)))
            .select_from(BaseProcessualEvento)
            .join(
                BaseProcessualProcesso,
                BaseProcessualEvento.processo_id == BaseProcessualProcesso.id,
            )
            .filter(BaseProcessualEvento.created_at >= day_start)
            .filter(BaseProcessualEvento.created_at < day_end)
            .filter(BaseProcessualEvento.tipo_evento == tipo)
        )
        if presenca_filter is not None:
            total = total.filter(
                BaseProcessualProcesso.presenca_status == presenca_filter
            )
        total = int(total.scalar() or 0)
        # Pra lista: pega o evento MAIS RECENTE por processo (DISTINCT ON processo_id).
        # PG-only mas estamos em PG. Em SQLite degrada pro evento mais antigo — OK pra dev.
        rows_raw = (
            q.order_by(
                BaseProcessualEvento.processo_id,
                BaseProcessualEvento.id.desc(),
            )
            .distinct(BaseProcessualEvento.processo_id)
            .all()
        )
        # ordena por id desc na ponta pra UI ver os recentes primeiro
        rows = sorted(rows_raw, key=lambda e: e.id, reverse=True)[:limit]
        out: list[BaseProcessualMovimentacaoItem] = []
        # pre-carrega processos pra evitar N+1
        proc_ids = [e.processo_id for e in rows]
        procs_map: dict[int, BaseProcessualProcesso] = {}
        if proc_ids:
            for p in (
                db.query(BaseProcessualProcesso)
                .filter(BaseProcessualProcesso.id.in_(proc_ids))
                .all()
            ):
                procs_map[p.id] = p
        for e in rows:
            p = procs_map.get(e.processo_id)
            distribuido_dt: Optional[datetime] = None
            if p and p.distribuido_em:
                distribuido_dt = datetime(
                    p.distribuido_em.year,
                    p.distribuido_em.month,
                    p.distribuido_em.day,
                )
            out.append(
                BaseProcessualMovimentacaoItem(
                    evento_id=e.id,
                    cod_ajus=e.cod_ajus,
                    numero_processo_mascarado=(
                        p.numero_processo_mascarado if p else None
                    ),
                    empresa=p.empresa if p else None,
                    uf=p.uf if p else None,
                    comarca=p.comarca if p else None,
                    usuario_responsavel=p.usuario_responsavel if p else None,
                    distribuido_em=distribuido_dt,
                    visto_em=e.created_at,
                    changed_fields=e.changed_fields,
                )
            )
        return total, out

    entraram_total, entraram = _items_for(EVENTO_ENTROU)
    sairam_total, sairam = _items_for(EVENTO_SAIU)
    atualizados_total, atualizados = _items_for(EVENTO_ATUALIZADO)

    return BaseProcessualMovimentacaoDoDiaResponse(
        data=day_start,
        entraram_total=entraram_total,
        sairam_total=sairam_total,
        atualizados_total=atualizados_total,
        entraram=entraram,
        sairam=sairam,
        atualizados=atualizados,
    )


# ============================================================================
# Processos (Chunk 3)
# ============================================================================

_PROCESSO_NORM_FIELDS = (
    "cod_ajus", "numero_processo", "numero_processo_mascarado",
    "numero_interno", "numero_pasta", "acao_principal", "materia",
    "risco_prob_perda", "tipo_acao", "polo", "natureza", "numero_vara",
    "foro", "comarca", "uf", "empresa", "grupo_responsavel",
    "usuario_responsavel", "escritorio_responsavel", "situacao_processo",
    "justica_honorario", "valor_causa", "valor_prev_acordo", "valor_acordo",
    "valor_discutido", "valor_exito", "valor_condenacao", "valor_contingencia",
    "ult_andamento", "data_ult_andamento", "dias_ult_atualizacao",
    "distribuido_em", "processo_virtual", "numero_contrato",
    "usuario_cadastro_acao", "data_cadastro_acao", "autores_raw", "reus_raw",
    "autores_json", "reus_json",
)


def _processo_to_norm(p: BaseProcessualProcesso) -> dict:
    return {k: getattr(p, k) for k in _PROCESSO_NORM_FIELDS}


@router.get("/processos", response_model=BaseProcessualProcessoListResponse)
def list_processos(
    presenca_status: Optional[str] = Query(None),
    cod_ajus: Optional[str] = Query(None),
    numero_pasta: Optional[str] = Query(None),
    empresa: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    comarca: Optional[str] = Query(None),
    situacao_processo: Optional[str] = Query(None),
    polo: Optional[str] = Query(None),
    materia: Optional[str] = Query(None),
    natureza: Optional[str] = Query(None),
    tipo_acao: Optional[str] = Query(None),
    risco_prob_perda: Optional[str] = Query(None),
    usuario_responsavel: Optional[str] = Query(None),
    grupo_responsavel: Optional[str] = Query(None),
    escritorio_responsavel: Optional[str] = Query(None),
    valor_causa_min: Optional[float] = Query(None),
    valor_causa_max: Optional[float] = Query(None),
    distribuido_de: Optional[date_type] = Query(None),
    distribuido_ate: Optional[date_type] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("ult_andamento_desc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Lista processos com filtros + busca + paginacao.

    Default: ATIVO_NA_BASE ordenado por ult_andamento_desc. Operador filtra
    pra encontrar carteira por UF/comarca/responsavel/situacao/etc.
    """
    q = db.query(BaseProcessualProcesso)

    if presenca_status:
        q = q.filter(BaseProcessualProcesso.presenca_status == presenca_status)
    if cod_ajus:
        q = q.filter(BaseProcessualProcesso.cod_ajus == cod_ajus)
    if numero_pasta:
        q = q.filter(BaseProcessualProcesso.numero_pasta == numero_pasta)
    if empresa:
        q = q.filter(BaseProcessualProcesso.empresa == empresa)
    if uf:
        q = q.filter(BaseProcessualProcesso.uf == uf.upper())
    if comarca:
        q = q.filter(BaseProcessualProcesso.comarca.ilike(f"%{comarca}%"))
    if situacao_processo:
        q = q.filter(BaseProcessualProcesso.situacao_processo == situacao_processo)
    if polo:
        q = q.filter(BaseProcessualProcesso.polo == polo)
    if materia:
        q = q.filter(BaseProcessualProcesso.materia == materia)
    if natureza:
        q = q.filter(BaseProcessualProcesso.natureza == natureza)
    if tipo_acao:
        q = q.filter(BaseProcessualProcesso.tipo_acao.ilike(f"%{tipo_acao}%"))
    if risco_prob_perda:
        q = q.filter(BaseProcessualProcesso.risco_prob_perda == risco_prob_perda)
    if usuario_responsavel:
        q = q.filter(
            BaseProcessualProcesso.usuario_responsavel.ilike(f"%{usuario_responsavel}%")
        )
    if grupo_responsavel:
        q = q.filter(BaseProcessualProcesso.grupo_responsavel == grupo_responsavel)
    if escritorio_responsavel:
        q = q.filter(
            BaseProcessualProcesso.escritorio_responsavel.ilike(
                f"%{escritorio_responsavel}%"
            )
        )
    if valor_causa_min is not None:
        q = q.filter(BaseProcessualProcesso.valor_causa >= valor_causa_min)
    if valor_causa_max is not None:
        q = q.filter(BaseProcessualProcesso.valor_causa <= valor_causa_max)
    if distribuido_de:
        q = q.filter(BaseProcessualProcesso.distribuido_em >= distribuido_de)
    if distribuido_ate:
        q = q.filter(BaseProcessualProcesso.distribuido_em <= distribuido_ate)

    # Busca livre multi-target: CNJ (digits >= 5), cod_ajus parcial,
    # numero_pasta, autores/reus via cast JSON->text + ILIKE.
    if search:
        s = search.strip()
        if s:
            digits = re.sub(r"[^0-9]", "", s)
            filters = []
            if digits and len(digits) >= 5:
                filters.append(
                    BaseProcessualProcesso.numero_processo.ilike(f"%{digits}%")
                )
            filters.append(BaseProcessualProcesso.cod_ajus.ilike(f"%{s}%"))
            filters.append(BaseProcessualProcesso.numero_pasta.ilike(f"%{s}%"))
            filters.append(
                sa_func.cast(
                    BaseProcessualProcesso.autores_json, sa_types.Text
                ).ilike(f"%{s}%")
            )
            filters.append(
                sa_func.cast(
                    BaseProcessualProcesso.reus_json, sa_types.Text
                ).ilike(f"%{s}%")
            )
            q = q.filter(sa_or(*filters))

    sort_map = {
        "ult_andamento_desc": BaseProcessualProcesso.data_ult_andamento.desc().nullslast(),
        "ult_andamento_asc": BaseProcessualProcesso.data_ult_andamento.asc().nullsfirst(),
        "cod_ajus_asc": BaseProcessualProcesso.cod_ajus.asc(),
        "cod_ajus_desc": BaseProcessualProcesso.cod_ajus.desc(),
        "valor_causa_desc": BaseProcessualProcesso.valor_causa.desc().nullslast(),
        "valor_causa_asc": BaseProcessualProcesso.valor_causa.asc().nullsfirst(),
        "distribuido_desc": BaseProcessualProcesso.distribuido_em.desc().nullslast(),
        "distribuido_asc": BaseProcessualProcesso.distribuido_em.asc().nullsfirst(),
        "updated_desc": BaseProcessualProcesso.updated_at.desc(),
    }
    q = q.order_by(sort_map.get(sort_by, sort_map["ult_andamento_desc"]))

    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualProcessoListResponse(
        total=total,
        items=[BaseProcessualProcessoOut.model_validate(p) for p in items],
    )


@router.get("/processos/{cod_ajus}", response_model=BaseProcessualProcessoOut)
def get_processo(
    cod_ajus: str,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Detalhe do processo (estado atual). Historico/eventos via outros endpoints."""
    p = (
        db.query(BaseProcessualProcesso)
        .filter(BaseProcessualProcesso.cod_ajus == cod_ajus)
        .first()
    )
    if p is None:
        raise HTTPException(
            status_code=404, detail=f"Processo {cod_ajus} nao encontrado."
        )
    return BaseProcessualProcessoOut.model_validate(p)


@router.get(
    "/processos/{cod_ajus}/historico",
    response_model=BaseProcessualSnapshotListResponse,
)
def get_processo_historico(
    cod_ajus: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Snapshots paginados do processo (mais recente primeiro)."""
    p = (
        db.query(BaseProcessualProcesso)
        .filter(BaseProcessualProcesso.cod_ajus == cod_ajus)
        .first()
    )
    if p is None:
        raise HTTPException(
            status_code=404, detail=f"Processo {cod_ajus} nao encontrado."
        )
    q = (
        db.query(BaseProcessualSnapshot)
        .filter(BaseProcessualSnapshot.processo_id == p.id)
        .order_by(BaseProcessualSnapshot.captured_at.desc())
    )
    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualSnapshotListResponse(
        total=total,
        items=[BaseProcessualSnapshotOut.model_validate(s) for s in items],
    )


@router.get(
    "/processos/{cod_ajus}/eventos",
    response_model=BaseProcessualEventoListResponse,
)
def get_processo_eventos(
    cod_ajus: str,
    tipo_evento: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Eventos do processo (cronologico desc, opcionalmente filtrado por tipo)."""
    p = (
        db.query(BaseProcessualProcesso)
        .filter(BaseProcessualProcesso.cod_ajus == cod_ajus)
        .first()
    )
    if p is None:
        raise HTTPException(
            status_code=404, detail=f"Processo {cod_ajus} nao encontrado."
        )
    q = (
        db.query(BaseProcessualEvento)
        .filter(BaseProcessualEvento.processo_id == p.id)
        .order_by(BaseProcessualEvento.created_at.desc())
    )
    if tipo_evento:
        q = q.filter(BaseProcessualEvento.tipo_evento == tipo_evento)
    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualEventoListResponse(
        total=total,
        items=[BaseProcessualEventoOut.model_validate(e) for e in items],
    )


@router.patch("/processos/{cod_ajus}", response_model=BaseProcessualProcessoOut)
def patch_processo(
    cod_ajus: str,
    payload: BaseProcessualProcessoPatch,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Override manual de campos editaveis. Gera snapshot + evento ATUALIZADO_MANUAL.

    Cria uma linha 'OVERRIDE_MANUAL' em base_processual_upload pra satisfazer
    a FK nao-nullable de snapshot/evento. Esse "upload virtual" carrega o
    motivo do override no error_message (audit trail).
    """
    p = (
        db.query(BaseProcessualProcesso)
        .filter(BaseProcessualProcesso.cod_ajus == cod_ajus)
        .first()
    )
    if p is None:
        raise HTTPException(
            status_code=404, detail=f"Processo {cod_ajus} nao encontrado."
        )

    changes = payload.model_dump(exclude_unset=True, exclude={"motivo"})
    if not changes:
        raise HTTPException(status_code=400, detail="Nenhum campo pra atualizar.")

    def _serialize(v):
        if v is None:
            return None
        if isinstance(v, (int, float, bool, str)):
            return v
        return str(v)

    changed_fields: dict[str, dict] = {}
    for k, v in changes.items():
        old = getattr(p, k, None)
        if old != v:
            changed_fields[k] = {"de": _serialize(old), "para": _serialize(v)}

    if not changed_fields:
        return BaseProcessualProcessoOut.model_validate(p)

    for k, v in changes.items():
        setattr(p, k, v)
    db.flush()

    now_utc = datetime.utcnow()
    override_upload = BaseProcessualUpload(
        filename=f"override-manual-{cod_ajus}-{now_utc.isoformat()}",
        file_sha256=None,
        file_bytes=None,
        total_rows_in_file=1,
        status="OVERRIDE_MANUAL",
        error_message=payload.motivo or None,
        uploaded_by_user_id=user.id,
        processed_at=now_utc,
        committed_at=now_utc,
    )
    db.add(override_upload)
    db.flush()

    norm = _processo_to_norm(p)
    snapshot = BaseProcessualSnapshot(
        processo_id=p.id,
        upload_id=override_upload.id,
        cod_ajus=p.cod_ajus,
        payload_normalized=_payload_normalized_json(norm),
        payload_raw=None,
        diff_hash=compute_diff_hash(norm),
    )
    db.add(snapshot)
    db.flush()

    prev_snapshot_id = p.current_snapshot_id
    p.current_snapshot_id = snapshot.id

    evento = BaseProcessualEvento(
        upload_id=override_upload.id,
        processo_id=p.id,
        cod_ajus=p.cod_ajus,
        tipo_evento=EVENTO_ATUALIZADO_MANUAL,
        changed_fields=changed_fields,
        snapshot_before_id=prev_snapshot_id,
        snapshot_after_id=snapshot.id,
    )
    db.add(evento)
    db.commit()
    db.refresh(p)
    return BaseProcessualProcessoOut.model_validate(p)


# ============================================================================
# Dashboard (Chunk 2 — mantido abaixo dos processos pra agrupar por tema)
# ============================================================================


@router.get(
    "/dashboard/inatividade",
    response_model=BaseProcessualInatividadeOut,
)
def dashboard_inatividade(
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Tempo desde ultimo upload CONCLUIDO. Alerta acima do threshold (env)."""
    threshold_h = int(os.environ.get("BASE_PROCESSUAL_UPLOAD_WARNING_HOURS", "24"))
    ultimo = (
        db.query(BaseProcessualUpload)
        .filter(BaseProcessualUpload.status == UPLOAD_STATUS_CONCLUIDO)
        .order_by(BaseProcessualUpload.committed_at.desc().nullslast())
        .first()
    )
    if ultimo is None:
        return BaseProcessualInatividadeOut(
            ultimo_upload_em=None,
            horas_desde_ultimo=None,
            alerta=True,
            threshold_horas=threshold_h,
        )
    last_at = ultimo.committed_at or ultimo.uploaded_at
    delta = datetime.utcnow().replace(tzinfo=None) - last_at.replace(tzinfo=None)
    horas = delta.total_seconds() / 3600.0
    return BaseProcessualInatividadeOut(
        ultimo_upload_em=last_at,
        horas_desde_ultimo=round(horas, 2),
        alerta=horas > threshold_h,
        threshold_horas=threshold_h,
    )
