"""Endpoints de auditoria + atualização em lote (Chunk 4).

Sao separados de `base_processual.py` (que ja' tem ~1k linhas) pra evitar
o limite de truncamento do Edit tool em arquivos grandes. Mesmo prefixo
de rotas — /api/v1/admin/base-processual/* — e mesmo require_admin.

Inclui:
- GET /eventos: auditoria cross-upload, filtros por tipo/upload/cod_ajus/data.
- POST /processos/bulk-update: aplica `set` em N processos que casam com
  `filter` (cap=1000), gera 1 upload virtual + N snapshots + N eventos
  ATUALIZADO_MANUAL. Idempotencia por contagem (confirm_count) pra evitar
  o operador clicar e a base ter crescido entre o preview e o commit.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func as sa_func, or_ as sa_or, types as sa_types
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    BaseProcessualBulkUpdatePayload,
    BaseProcessualBulkUpdateResult,
    BaseProcessualEventoListResponse,
    BaseProcessualEventoOut,
)
from app.api.v1.endpoints.base_processual import (
    _payload_normalized_json,
    _processo_to_norm,
    require_admin,
)
from app.core.dependencies import get_db
from app.models.base_processual import (
    BaseProcessualEvento,
    BaseProcessualProcesso,
    BaseProcessualSnapshot,
    BaseProcessualUpload,
    EVENTO_ATUALIZADO_MANUAL,
)
from app.models.legal_one import LegalOneUser
from app.services.base_processual.diff import compute_diff_hash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/base-processual", tags=["Base Processual"])


# Cap de seguranca pra evitar bulk update gigantesco acidental.
# Operador que precisa atualizar >1000 deve refinar filtro ou abrir ticket.
BULK_UPDATE_MAX = 1000


@router.get("/eventos", response_model=BaseProcessualEventoListResponse)
def list_eventos_cross_upload(
    tipo_evento: Optional[str] = Query(
        None,
        description="CSV — multiplos tipos separados por virgula. Ex.: 'ENTROU,SAIU'.",
    ),
    upload_id: Optional[int] = Query(None),
    cod_ajus: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    search: Optional[str] = Query(
        None, description="cod_ajus parcial (ILIKE)"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Eventos paginados cross-upload — auditoria geral do modulo.

    Default: mais recente primeiro (created_at desc). Filtros opcionais
    combinam por AND. tipo_evento aceita CSV pra multi-select.
    """
    q = db.query(BaseProcessualEvento).order_by(
        BaseProcessualEvento.id.desc()
    )
    if tipo_evento:
        tipos = [t.strip().upper() for t in tipo_evento.split(",") if t.strip()]
        if tipos:
            q = q.filter(BaseProcessualEvento.tipo_evento.in_(tipos))
    if upload_id is not None:
        q = q.filter(BaseProcessualEvento.upload_id == upload_id)
    if cod_ajus:
        q = q.filter(BaseProcessualEvento.cod_ajus == cod_ajus)
    if from_date:
        q = q.filter(BaseProcessualEvento.created_at >= from_date)
    if to_date:
        q = q.filter(BaseProcessualEvento.created_at <= to_date)
    if search:
        q = q.filter(BaseProcessualEvento.cod_ajus.ilike(f"%{search}%"))

    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualEventoListResponse(
        total=total,
        items=[BaseProcessualEventoOut.model_validate(e) for e in items],
    )


def _apply_filter_to_query(q, filt) -> "Session.query":
    """Aplica os mesmos filtros do GET /processos numa query de BaseProcessualProcesso.

    Reutilizado por bulk-update + bulk-preview. `filt` e' um
    BaseProcessualBulkUpdateFilters (model com mesmos campos do GET).
    """
    if filt.presenca_status:
        q = q.filter(BaseProcessualProcesso.presenca_status == filt.presenca_status)
    if filt.cod_ajus_list:
        q = q.filter(BaseProcessualProcesso.cod_ajus.in_(filt.cod_ajus_list))
    if filt.empresa:
        q = q.filter(BaseProcessualProcesso.empresa == filt.empresa)
    if filt.uf:
        q = q.filter(BaseProcessualProcesso.uf == filt.uf.upper())
    if filt.comarca:
        q = q.filter(BaseProcessualProcesso.comarca.ilike(f"%{filt.comarca}%"))
    if filt.situacao_processo:
        q = q.filter(
            BaseProcessualProcesso.situacao_processo == filt.situacao_processo
        )
    if filt.polo:
        q = q.filter(BaseProcessualProcesso.polo == filt.polo)
    if filt.materia:
        q = q.filter(BaseProcessualProcesso.materia == filt.materia)
    if filt.natureza:
        q = q.filter(BaseProcessualProcesso.natureza == filt.natureza)
    if filt.tipo_acao:
        q = q.filter(BaseProcessualProcesso.tipo_acao.ilike(f"%{filt.tipo_acao}%"))
    if filt.risco_prob_perda:
        q = q.filter(BaseProcessualProcesso.risco_prob_perda == filt.risco_prob_perda)
    if filt.usuario_responsavel:
        q = q.filter(
            BaseProcessualProcesso.usuario_responsavel.ilike(
                f"%{filt.usuario_responsavel}%"
            )
        )
    if filt.grupo_responsavel:
        q = q.filter(BaseProcessualProcesso.grupo_responsavel == filt.grupo_responsavel)
    if filt.escritorio_responsavel:
        q = q.filter(
            BaseProcessualProcesso.escritorio_responsavel.ilike(
                f"%{filt.escritorio_responsavel}%"
            )
        )
    if filt.valor_causa_min is not None:
        q = q.filter(BaseProcessualProcesso.valor_causa >= filt.valor_causa_min)
    if filt.valor_causa_max is not None:
        q = q.filter(BaseProcessualProcesso.valor_causa <= filt.valor_causa_max)
    if filt.distribuido_de:
        q = q.filter(BaseProcessualProcesso.distribuido_em >= filt.distribuido_de)
    if filt.distribuido_ate:
        q = q.filter(BaseProcessualProcesso.distribuido_em <= filt.distribuido_ate)
    if filt.search:
        s = filt.search.strip()
        if s:
            digits = re.sub(r"[^0-9]", "", s)
            sub_filters = []
            if digits and len(digits) >= 5:
                sub_filters.append(
                    BaseProcessualProcesso.numero_processo.ilike(f"%{digits}%")
                )
            sub_filters.append(BaseProcessualProcesso.cod_ajus.ilike(f"%{s}%"))
            sub_filters.append(BaseProcessualProcesso.numero_pasta.ilike(f"%{s}%"))
            sub_filters.append(
                sa_func.cast(
                    BaseProcessualProcesso.autores_json, sa_types.Text
                ).ilike(f"%{s}%")
            )
            sub_filters.append(
                sa_func.cast(
                    BaseProcessualProcesso.reus_json, sa_types.Text
                ).ilike(f"%{s}%")
            )
            q = q.filter(sa_or(*sub_filters))
    return q


@router.post(
    "/processos/bulk-update",
    response_model=BaseProcessualBulkUpdateResult,
)
def bulk_update_processos(
    payload: BaseProcessualBulkUpdatePayload,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Aplica `set` em N processos que casam com `filter` numa transacao.

    - Cap = 1000 processos por requisicao (HTTP 409 se ultrapassar).
    - Se `confirm_count` for enviado, valida contra o total real — protege
      contra race entre preview e commit.
    - Gera 1 upload virtual (status=BULK_UPDATE) + N snapshots novos +
      N eventos ATUALIZADO_MANUAL — mesmas estruturas do PATCH individual.
    - Falha se nenhum campo de `set` foi enviado.
    """
    set_changes = payload.set.model_dump(exclude_unset=True, exclude_none=True)
    if not set_changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum campo em 'set' — informe ao menos um campo pra atualizar.",
        )

    q = _apply_filter_to_query(
        db.query(BaseProcessualProcesso), payload.filter
    )

    total = q.count()
    if total == 0:
        return BaseProcessualBulkUpdateResult(
            total_afetados=0,
            cods_afetados=[],
            upload_id=0,
            eventos_criados=0,
        )
    if total > BULK_UPDATE_MAX:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{total} processos casam o filtro — limite por bulk e' "
                f"{BULK_UPDATE_MAX}. Refine o filtro ou faca em lotes."
            ),
        )
    if payload.confirm_count is not None and payload.confirm_count != total:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Total atual ({total}) difere do confirm_count enviado "
                f"({payload.confirm_count}). Recarregue o preview antes de confirmar."
            ),
        )

    # Upload virtual pra satisfazer FK NOT NULL de snapshot/evento.
    now_utc = datetime.utcnow()
    upload = BaseProcessualUpload(
        filename=f"bulk-update-{now_utc.isoformat()}-{user.id}",
        file_sha256=None,
        file_bytes=None,
        total_rows_in_file=total,
        status="BULK_UPDATE",
        error_message=payload.motivo or None,
        uploaded_by_user_id=user.id,
        processed_at=now_utc,
        committed_at=now_utc,
    )
    db.add(upload)
    db.flush()

    def _ser(v):
        if v is None:
            return None
        if isinstance(v, (int, float, bool, str)):
            return v
        return str(v)

    processos = q.all()

    # Fase 1: calcular diffs (sem escrita)
    pending: list[tuple[BaseProcessualProcesso, dict[str, dict]]] = []
    for p in processos:
        changed: dict[str, dict] = {}
        for k, v in set_changes.items():
            old = getattr(p, k, None)
            if old != v:
                changed[k] = {"de": _ser(old), "para": _ser(v)}
        if changed:
            pending.append((p, changed))

    if not pending:
        # Tudo casado ja' tinha o valor — nada a aplicar
        upload.summary_inalterados = total
        upload.summary_atualizados = 0
        db.commit()
        return BaseProcessualBulkUpdateResult(
            total_afetados=total,
            cods_afetados=[],
            upload_id=upload.id,
            eventos_criados=0,
        )

    # Fase 2: aplica mudancas em memoria
    for p, _ in pending:
        for k, v in set_changes.items():
            setattr(p, k, v)
    db.flush()

    # Fase 3: cria snapshots em lote (1 flush)
    snapshot_pairs: list[tuple[BaseProcessualProcesso, BaseProcessualSnapshot, dict]] = []
    for p, changed in pending:
        norm = _processo_to_norm(p)
        s = BaseProcessualSnapshot(
            processo_id=p.id,
            upload_id=upload.id,
            cod_ajus=p.cod_ajus,
            payload_normalized=_payload_normalized_json(norm),
            payload_raw=None,
            diff_hash=compute_diff_hash(norm),
        )
        db.add(s)
        snapshot_pairs.append((p, s, changed))
    db.flush()

    # Fase 4: linkar processos a snapshot + criar eventos
    for p, s, changed in snapshot_pairs:
        prev_snapshot_id = p.current_snapshot_id
        p.current_snapshot_id = s.id
        e = BaseProcessualEvento(
            upload_id=upload.id,
            processo_id=p.id,
            cod_ajus=p.cod_ajus,
            tipo_evento=EVENTO_ATUALIZADO_MANUAL,
            changed_fields=changed,
            snapshot_before_id=prev_snapshot_id,
            snapshot_after_id=s.id,
        )
        db.add(e)

    upload.summary_atualizados = len(pending)
    upload.summary_inalterados = total - len(pending)
    db.commit()

    return BaseProcessualBulkUpdateResult(
        total_afetados=total,
        cods_afetados=[p.cod_ajus for p, _ in pending],
        upload_id=upload.id,
        eventos_criados=len(pending),
    )
