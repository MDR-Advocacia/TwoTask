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
from datetime import date
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
    - Tamanho max: 30MB (matches base_processual)
    - Header obrigatorio: cnj (na linha 1 ou 2)
    """
    # Limite de 30MB
    content = file.file.read()
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="Arquivo maior que 30MB. Tente um arquivo menor.",
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
        lote = create_lote_from_prazos_iniciais(
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
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao criar lote a partir de Prazos Iniciais.")
        raise HTTPException(
            status_code=500, detail=f"Erro inesperado: {type(exc).__name__}: {exc}"
        )

    return {"lote": _serialize_lote(lote)}


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
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista paginada de processos do lote. Filtros: status, source, categoria, polo, cnj."""
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
    ou >30MB), aquele e' marcado como ERRO_CAPTURA e os outros seguem.
    Se TODOS falharem, o lote e' deletado e a request retorna 400.

    Depois operador classifica via UI (botao ✨ no historico) ou worker.

    Returns:
        { lote: {...}, processos: [{...}, ...] }  — 1 entrada por PDF.
    """
    from datetime import datetime as _dt

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
        if len(content) > 30 * 1024 * 1024:
            pdfs.append((f.filename or "?.pdf", b"", "Arquivo > 30MB."))
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

    # 1) Cria lote
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
                "Verifique se os arquivos sao PDFs validos e <= 30MB."
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
    - `file` (obrig.): PDF (≤ tamanho max do settings.prazos_iniciais_max_pdf_mb)
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
