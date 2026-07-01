"""
Endpoints do módulo "Análise Recursal" (dentro de Prazos Processuais).

Fluxo:
  1. POST /recursal/upload         — operador sobe 1 PDF de processo
     (frontend faz loop pra subir vários). Reusa o extractor mecânico de
     Prazos Iniciais → capa+integra. Sem CNJ obrigatório: o nº do
     processo vem do NOME do arquivo.
  2. POST /recursal/submit         — junta os RECEBIDOS e dispara 1 batch
     Sonnet (~R$0,17/processo).
  3. POST /recursal/batches/{id}/refresh — polling; quando o batch termina,
     aplica os vereditos + calcula o custo determinístico.
  4. GET  /recursal                — listagem paginada {total, items}.

Tudo atrás de JWT + permissão `prazos_iniciais` (mesmo grupo do módulo).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, List, Optional

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
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.models.analise_recursal import (
    RCR_STATUS_RECEBIDO,
    RCR_STATUS_SEM_TEXTO,
    AnaliseRecursal,
    AnaliseRecursalBatch,
    RecursalCustaTabela,
)
from app.services.recursal.classifier import RecursalBatchClassifier
from app.services.recursal.cost_calculator import calcular_custo, derive_uf_from_cnj
from app.services.recursal.parecer import render_assunto, render_parecer
from app.services.recursal.produtos import categoria_de
from app.services.prazos_iniciais.pdf_extractor import extract as pdf_extract
from app.services.prazos_iniciais.storage import (
    PdfValidationError,
    validate_pdf_bytes,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recursal", tags=["Análise Recursal"])


# ─── Serialização ─────────────────────────────────────────────────────


def _num(v) -> Optional[float]:
    return float(v) if v is not None else None


def _analise_to_dict(an: AnaliseRecursal, db: Optional[Session] = None) -> dict[str, Any]:
    analisado = an.status == "ANALISADO"
    custo = _num(an.custo_estimado)
    # Recompute pra DISPLAY quando ainda não há custo mas a tabela de custas
    # já pode ter sido cadastrada (não persiste — só exibe).
    if (
        custo is None
        and db is not None
        and analisado
        and an.valor_causa is not None
    ):
        novo, _det = calcular_custo(
            db,
            uf=an.uf,
            tipo_recurso=an.tipo_recurso,
            valor_causa=float(an.valor_causa),
        )
        if novo is not None:
            custo = novo

    return {
        "id": an.id,
        "processo_numero": an.processo_numero,
        "cnj_number": an.cnj_number,
        "uf": an.uf,
        "tribunal": an.tribunal,
        "status": an.status,
        "extraction_confidence": an.extraction_confidence,
        "extraction_failed": bool(an.extraction_failed),
        "extractor_used": an.extractor_used,
        "pdf_filename_original": an.pdf_filename_original,
        "error_message": an.error_message,
        # identificação
        "nome_autor": an.nome_autor,
        "cpf": an.cpf,
        "objeto": an.objeto,
        "produto": an.produto,
        "produto_categoria": categoria_de(an.produto),
        # veredito
        "resultado_decisao": an.resultado_decisao,
        "tipo_decisao": an.tipo_decisao,
        "resumo_topicos": an.resumo_topicos or [],
        "destaque": an.destaque,
        "fundamentacao_juiz": an.fundamentacao_juiz,
        "pontos_analise": an.pontos_analise or [],
        "probabilidade_reversao": an.probabilidade_reversao,
        "recorrer": an.recorrer,
        "tipo_recurso": an.tipo_recurso,
        "fundamentacao": an.fundamentacao,
        "valor_causa": _num(an.valor_causa),
        "valor_condenacao": an.valor_condenacao,
        "prazo_fatal": an.prazo_fatal.isoformat() if an.prazo_fatal else None,
        "custo_estimado": custo,
        "custo_detalhe": an.custo_detalhe,
        "confianca": an.confianca,
        # parecer renderizado (pronto pra copiar)
        "assunto": render_assunto(an),
        "parecer_texto": render_parecer(an, custo) if analisado else None,
        "analysis_batch_id": an.analysis_batch_id,
        "uploaded_by_email": an.uploaded_by_email,
        "uploaded_by_name": an.uploaded_by_name,
        "created_at": an.created_at.isoformat() if an.created_at else None,
        "analyzed_at": an.analyzed_at.isoformat() if an.analyzed_at else None,
    }


def _processo_numero_from_filename(filename: Optional[str]) -> str:
    """Deriva o número do processo do nome do arquivo (sem extensão)."""
    if not filename:
        return "sem-numero"
    base = os.path.basename(filename)
    stem, _ext = os.path.splitext(base)
    stem = stem.strip()
    return stem or "sem-numero"


# ─── Upload (1 PDF; frontend faz loop) ────────────────────────────────


class UploadResponse(BaseModel):
    id: int
    processo_numero: str
    cnj_number: Optional[str] = None
    uf: Optional[str] = None
    status: str
    extraction_confidence: Optional[str] = None
    extraction_failed: bool = False
    already_existed: bool = False
    user_message: Optional[str] = None


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Operador sobe 1 PDF de processo para análise recursal.",
)
async def upload_processo(
    processo_pdf: UploadFile = File(
        ..., description="PDF do processo na íntegra (nomeado pelo nº do processo)."
    ),
    processo_numero: Optional[str] = Form(
        default=None,
        description="(Opcional) nº do processo; default = nome do arquivo.",
    ),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(
        auth_security.require_permission("prazos_iniciais")
    ),
):
    max_bytes = settings.prazos_iniciais_max_upload_pdf_bytes
    pdf_bytes = await processo_pdf.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O arquivo está vazio.",
        )
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"O PDF excede {settings.prazos_iniciais_max_upload_pdf_mb} MB "
                f"(recebido: {len(pdf_bytes) / 1024 / 1024:.1f} MB)."
            ),
        )
    try:
        validate_pdf_bytes(pdf_bytes)
    except PdfValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Arquivo inválido: {exc}",
        )

    numero = (processo_numero or "").strip() or _processo_numero_from_filename(
        processo_pdf.filename
    )
    sha = hashlib.sha256(pdf_bytes).hexdigest()

    # Idempotência por SHA — re-subir o mesmo PDF devolve a análise existente.
    existing = (
        db.query(AnaliseRecursal)
        .filter(AnaliseRecursal.pdf_sha256 == sha)
        .first()
    )
    if existing is not None:
        return UploadResponse(
            id=existing.id,
            processo_numero=existing.processo_numero,
            cnj_number=existing.cnj_number,
            uf=existing.uf,
            status=existing.status,
            extraction_confidence=existing.extraction_confidence,
            extraction_failed=bool(existing.extraction_failed),
            already_existed=True,
            user_message="Este PDF já tinha sido enviado antes.",
        )

    # Extração mecânica (reusa o motor de Prazos Iniciais).
    extraction = pdf_extract(pdf_bytes)

    integra = extraction.integra_json or {}
    integra_has_content = bool(
        integra.get("timeline") or (integra.get("texto_cru") or "").strip()
    )
    useful = bool(extraction.success and integra_has_content)

    an_status = RCR_STATUS_RECEBIDO if useful else RCR_STATUS_SEM_TEXTO
    cnj = extraction.cnj_number
    uf = derive_uf_from_cnj(cnj)

    an = AnaliseRecursal(
        processo_numero=numero,
        cnj_number=cnj,
        uf=uf,
        capa_json=extraction.capa_json or {},
        integra_json=extraction.integra_json or {},
        extractor_used=extraction.extractor_used,
        extraction_confidence=extraction.confidence,
        extraction_failed=not extraction.success,
        pdf_sha256=sha,
        pdf_filename_original=processo_pdf.filename,
        pdf_bytes=len(pdf_bytes),
        status=an_status,
        uploaded_by_user_id=current_user.id,
        uploaded_by_email=current_user.email,
        uploaded_by_name=current_user.name,
    )
    db.add(an)
    db.commit()
    db.refresh(an)

    msg = None
    if an_status == RCR_STATUS_SEM_TEXTO:
        msg = (
            "PDF sem texto extraível (provavelmente escaneado). O processo "
            "foi cadastrado, mas não entra na análise automática."
        )
    return UploadResponse(
        id=an.id,
        processo_numero=an.processo_numero,
        cnj_number=an.cnj_number,
        uf=an.uf,
        status=an.status,
        extraction_confidence=an.extraction_confidence,
        extraction_failed=bool(an.extraction_failed),
        already_existed=False,
        user_message=msg,
    )


# ─── Submit batch ─────────────────────────────────────────────────────


@router.post("/submit", summary="Dispara o batch de análise dos processos RECEBIDOS.")
async def submit_analise(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(
        auth_security.require_permission("prazos_iniciais")
    ),
):
    classifier = RecursalBatchClassifier(db=db)
    pending = classifier.collect_pending()
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum processo aguardando análise (status RECEBIDO).",
        )
    batch = await classifier.submit_batch(
        pending, requested_by_email=current_user.email
    )
    return {
        "batch": classifier.batch_to_dict(batch),
        "submetidos": len(pending),
    }


# ─── Listagem ─────────────────────────────────────────────────────────


@router.get("", summary="Lista análises recursais (paginado).")
@router.get("/", include_in_schema=False)
def list_analises(
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(AnaliseRecursal)
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
        if len(statuses) == 1:
            query = query.filter(AnaliseRecursal.status == statuses[0])
        elif statuses:
            query = query.filter(AnaliseRecursal.status.in_(statuses))

    total = query.count()
    rows = (
        query.order_by(AnaliseRecursal.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": [_analise_to_dict(r, db) for r in rows]}


@router.get("/progresso", summary="Contagem por status (barra de progresso).")
def progresso(
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    rows = (
        db.query(AnaliseRecursal.status, func.count(AnaliseRecursal.id))
        .group_by(AnaliseRecursal.status)
        .all()
    )
    c = {status: n for status, n in rows}
    recebido = c.get("RECEBIDO", 0)
    em_analise = c.get("EM_ANALISE", 0)
    analisado = c.get("ANALISADO", 0)
    erro = c.get("ERRO_ANALISE", 0)
    sem_texto = c.get("SEM_TEXTO", 0)
    # "em jogo" = tudo que é analisável (exclui os sem texto).
    em_jogo = recebido + em_analise + analisado + erro
    terminados = analisado + erro
    return {
        "total": sum(c.values()),
        "recebido": recebido,
        "em_analise": em_analise,
        "analisado": analisado,
        "erro": erro,
        "sem_texto": sem_texto,
        "em_jogo": em_jogo,
        "terminados": terminados,
        "processando": recebido + em_analise,
        "pct": round(100 * terminados / em_jogo) if em_jogo else 0,
    }


@router.get("/{analise_id}", summary="Detalhe de uma análise recursal.")
def get_analise(
    analise_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    an = (
        db.query(AnaliseRecursal)
        .filter(AnaliseRecursal.id == analise_id)
        .first()
    )
    if not an:
        raise HTTPException(status_code=404, detail="Análise não encontrada.")
    return _analise_to_dict(an, db)


@router.delete("/{analise_id}", summary="Remove uma análise recursal.")
def delete_analise(
    analise_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    an = (
        db.query(AnaliseRecursal)
        .filter(AnaliseRecursal.id == analise_id)
        .first()
    )
    if not an:
        raise HTTPException(status_code=404, detail="Análise não encontrada.")
    db.delete(an)
    db.commit()
    return {"ok": True}


# ─── Batches ──────────────────────────────────────────────────────────


@router.get("/batches/list", summary="Lista batches de análise recursal.")
def list_batches(
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    classifier = RecursalBatchClassifier(db=db)
    total = classifier.count_batches()
    rows = classifier.list_batches(limit=limit, offset=offset)
    return {"total": total, "items": [classifier.batch_to_dict(b) for b in rows]}


@router.post(
    "/batches/{batch_id}/refresh",
    summary="Atualiza o status do batch; aplica os vereditos quando termina.",
)
async def refresh_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    classifier = RecursalBatchClassifier(db=db)
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")

    batch = await classifier.refresh_batch_status(batch)
    summary = None
    # Quando o batch terminou e ainda não foi aplicado, aplica agora.
    if batch.results_url and batch.applied_at is None:
        summary = await classifier.apply_batch_results(batch)

    return {"batch": classifier.batch_to_dict(batch), "summary": summary}


# ─── Custas (tabela alimentada pelo operador) ─────────────────────────


class CustaIn(BaseModel):
    uf: str
    tribunal: Optional[str] = None
    tipo_recurso: str
    percentual: float = 0
    valor_fixo: float = 0
    valor_minimo: Optional[float] = None
    valor_maximo: Optional[float] = None
    porte_remessa_retorno: float = 0
    vigencia: Optional[str] = None
    fundamentacao: Optional[str] = None
    ativo: bool = True


class CustasBulkIn(BaseModel):
    rows: List[CustaIn] = Field(default_factory=list)
    replace: bool = False  # se True, zera a tabela antes de inserir


def _custa_to_dict(c: RecursalCustaTabela) -> dict[str, Any]:
    return {
        "id": c.id,
        "uf": c.uf,
        "tribunal": c.tribunal,
        "tipo_recurso": c.tipo_recurso,
        "percentual": _num(c.percentual),
        "valor_fixo": _num(c.valor_fixo),
        "valor_minimo": _num(c.valor_minimo),
        "valor_maximo": _num(c.valor_maximo),
        "porte_remessa_retorno": _num(c.porte_remessa_retorno),
        "vigencia": c.vigencia,
        "fundamentacao": c.fundamentacao,
        "ativo": bool(c.ativo),
    }


@router.get("/custas/list", summary="Lista a tabela de custas por estado.")
def list_custas(
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    rows = (
        db.query(RecursalCustaTabela)
        .order_by(RecursalCustaTabela.uf, RecursalCustaTabela.tipo_recurso)
        .all()
    )
    return {"total": len(rows), "items": [_custa_to_dict(r) for r in rows]}


@router.post("/custas", summary="Insere/atualiza linhas de custas (bulk).")
def upsert_custas(
    body: CustasBulkIn,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    if body.replace:
        db.query(RecursalCustaTabela).delete()

    inserted = 0
    for r in body.rows:
        db.add(
            RecursalCustaTabela(
                uf=r.uf.strip().upper(),
                tribunal=r.tribunal,
                tipo_recurso=r.tipo_recurso.strip().upper(),
                percentual=r.percentual,
                valor_fixo=r.valor_fixo,
                valor_minimo=r.valor_minimo,
                valor_maximo=r.valor_maximo,
                porte_remessa_retorno=r.porte_remessa_retorno,
                vigencia=r.vigencia,
                fundamentacao=r.fundamentacao,
                ativo=r.ativo,
            )
        )
        inserted += 1
    db.commit()
    return {"inserted": inserted, "replaced": body.replace}


@router.post(
    "/custas/recompute",
    summary="Recalcula o custo das análises com a tabela de custas atual.",
)
def recompute_custos(
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    rows = (
        db.query(AnaliseRecursal)
        .filter(AnaliseRecursal.status == "ANALISADO")
        .filter(AnaliseRecursal.valor_causa.isnot(None))
        .all()
    )
    atualizadas = 0
    for an in rows:
        custo, detalhe = calcular_custo(
            db,
            uf=an.uf,
            tipo_recurso=an.tipo_recurso,
            valor_causa=float(an.valor_causa),
        )
        if custo != _num(an.custo_estimado):
            an.custo_estimado = custo
            an.custo_detalhe = detalhe
            atualizadas += 1
    db.commit()
    return {"recalculadas": atualizadas, "total_analisadas": len(rows)}


@router.delete("/custas/{custa_id}", summary="Remove uma linha de custas.")
def delete_custa(
    custa_id: int,
    db: Session = Depends(get_db),
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    c = (
        db.query(RecursalCustaTabela)
        .filter(RecursalCustaTabela.id == custa_id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Linha de custas não encontrada.")
    db.delete(c)
    db.commit()
    return {"ok": True}
