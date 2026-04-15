"""
Endpoints do motor de busca de publicações do Legal One.

Rotas:
  GET    /statistics                     → Contagens para o dashboard
  POST   /search                         → Dispara uma nova busca
  GET    /searches                       → Lista buscas anteriores
  GET    /searches/{id}                  → Detalhe de uma busca
  POST   /searches/{id}/cancel           → Cancela busca em andamento
  GET    /records                        → Lista registros de publicações (filtros)
  GET    /records/grouped                → Lista registros agrupados por processo
  GET    /records/{id}                   → Detalhe de um registro
  PATCH  /records/{id}                   → Atualiza status de um registro
  POST   /groups/{lawsuit_id}/schedule   → Agenda tarefa para um grupo (processo)
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db, get_api_client
from app.services.legal_one_client import LegalOneApiClient
from app.services.publication_batch_classifier import PublicationBatchClassifier
from app.services.publication_export_service import export_records_grouped_xlsx
from app.services.publication_search_service import PublicationSearchService

router = APIRouter()


def _get_batch_classifier(
    db: Session = Depends(get_db),
) -> PublicationBatchClassifier:
    return PublicationBatchClassifier(db=db)


def _get_service(
    db: Session = Depends(get_db),
    client: LegalOneApiClient = Depends(get_api_client),
) -> PublicationSearchService:
    return PublicationSearchService(db=db, client=client)


# ─── Schemas ────────────────────────────────────

class SearchRequest(BaseModel):
    date_from: str
    date_to: Optional[str] = None
    origin_type: str = "OfficialJournalsCrawler"
    responsible_office_id: Optional[int] = None
    auto_classify: bool = True


class UpdateRecordStatusRequest(BaseModel):
    status: str


class ScheduleGroupRequest(BaseModel):
    # Permite que o operador edite o payload proposto antes de enviar (1 tarefa)
    payload_override: Optional[dict] = None
    # Permite enviar várias tarefas numa única chamada (N tarefas → 1 agendamento)
    payload_overrides: Optional[list[dict]] = None
    # Se vazio, usa todos os registros do processo; se informado, só esses
    record_ids: Optional[list[int]] = None


class ScheduleRecordsRequest(BaseModel):
    """Agendamento para publicações sem processo vinculado."""
    record_ids: list[int]
    payload_override: Optional[dict] = None
    payload_overrides: Optional[list[dict]] = None


class ReclassifyRecordsRequest(BaseModel):
    """Override manual de categoria/subcategoria de um conjunto de publicações."""
    record_ids: list[int]
    category: str
    subcategory: Optional[str] = None


# ─── Dashboard ──────────────────────────────────

@router.get("/statistics")
async def get_statistics(
    service: PublicationSearchService = Depends(_get_service),
):
    """Retorna contagens gerais para o painel de controle."""
    return service.get_statistics()


# ─── Buscas ─────────────────────────────────────

@router.post("/search")
async def create_search(
    payload: SearchRequest,
    background_tasks: BackgroundTasks,
    service: PublicationSearchService = Depends(_get_service),
    current_user=Depends(auth_security.get_current_user),
):
    """Dispara uma nova busca de publicações no Legal One."""
    import logging
    logger = logging.getLogger(__name__)

    def _run_search():
        try:
            service.create_and_run_search(
                date_from=payload.date_from,
                date_to=payload.date_to,
                origin_type=payload.origin_type,
                responsible_office_id=payload.responsible_office_id,
                auto_classify=payload.auto_classify,
                requested_by=current_user.email if hasattr(current_user, "email") else None,
            )
        except Exception as exc:
            logger.error("Erro na busca de publicacoes: %s", exc)

    background_tasks.add_task(_run_search)
    return {"message": "Busca iniciada em background.", "status": "EXECUTANDO"}


@router.post("/reclassify")
async def reclassify_pending(
    background_tasks: BackgroundTasks,
    linked_office_id: Optional[int] = None,
    service: PublicationSearchService = Depends(_get_service),
    _=Depends(auth_security.get_current_user),
):
    """
    Reclassifica todos os registros com status NOVO que ainda têm texto.
    Útil para processar registros de buscas anteriores sem classificação.
    Aceita filtro opcional por escritório responsável (linked_office_id).
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    def _run():
        try:
            records = service.list_novo_with_text(linked_office_id=linked_office_id)
            if not records:
                _logger.info("Nenhum registro NOVO com texto para reclassificar.")
                return
            _logger.info("Reclassificando %d registros NOVO...", len(records))
            service._auto_classify_records(records)
            service._build_task_proposals(records)
        except Exception as exc:
            _logger.error("Erro na reclassificação: %s", exc)

    background_tasks.add_task(_run)
    return {"message": "Reclassificação iniciada em background.", "status": "EXECUTANDO"}


@router.post("/rebuild-proposals")
async def rebuild_task_proposals(
    background_tasks: BackgroundTasks,
    linked_office_id: Optional[int] = None,
    service: PublicationSearchService = Depends(_get_service),
    _=Depends(auth_security.get_current_user),
):
    """
    Reconstrói propostas de tarefa para todos os registros já classificados
    que ainda não possuem proposta (ou para todos, se force=True).

    Útil quando um novo template é criado e os registros já foram classificados
    antes da criação do template.
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    def _run():
        try:
            from app.models.publication_search import PublicationRecord as PR, RECORD_STATUS_CLASSIFIED
            q = service.db.query(PR).filter(
                PR.status == RECORD_STATUS_CLASSIFIED,
                PR.category.isnot(None),
            )
            if linked_office_id:
                q = q.filter(PR.linked_office_id == linked_office_id)
            records = q.all()
            if not records:
                _logger.info("Nenhum registro classificado encontrado para reconstrução de propostas.")
                return
            _logger.info("Reconstruindo propostas para %d registros classificados...", len(records))
            # skip_responsible_lookup=True evita N chamadas à API Legal One que causam rate-limit (429).
            # O responsável pode ser definido manualmente na hora do agendamento.
            service._build_task_proposals(records, skip_responsible_lookup=True)
            _logger.info("Reconstrução de propostas concluída.")
        except Exception as exc:
            _logger.error("Erro na reconstrução de propostas: %s", exc)

    background_tasks.add_task(_run)
    return {"message": "Reconstrução de propostas iniciada em background.", "status": "EXECUTANDO"}


# ─── Classificação em lote (Anthropic Batch API) ────────────────────────

class SubmitBatchRequest(BaseModel):
    linked_office_id: Optional[int] = None
    limit: Optional[int] = None


@router.post("/classify-batch/submit")
async def submit_classify_batch(
    payload: SubmitBatchRequest,
    classifier: PublicationBatchClassifier = Depends(_get_batch_classifier),
    current_user=Depends(auth_security.get_current_user),
):
    """
    Envia publicações pendentes (NOVO, com texto, sem categoria) para
    a Message Batches API da Anthropic.

    Este endpoint é SÍNCRONO no que diz respeito à criação do batch
    (retorna o anthropic_batch_id imediatamente), mas a classificação
    das publicações acontece ASSINCRONAMENTE no lado da Anthropic.

    Aceita filtro por escritório e limite de registros.
    """
    records = classifier.collect_pending_records(
        linked_office_id=payload.linked_office_id,
        limit=payload.limit,
    )
    if not records:
        raise HTTPException(
            status_code=404,
            detail="Nenhum registro pendente de classificação encontrado.",
        )

    try:
        email = current_user.email if hasattr(current_user, "email") else None
        batch = await classifier.submit_batch(
            records=records, requested_by_email=email
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao enviar batch para Anthropic: {exc}",
        )

    return classifier.batch_to_dict(batch)


@router.get("/classify-batch")
async def list_classify_batches(
    limit: int = Query(50, ge=1, le=200),
    classifier: PublicationBatchClassifier = Depends(_get_batch_classifier),
    _=Depends(auth_security.get_current_user),
):
    """Lista os batches de classificação mais recentes."""
    batches = classifier.list_batches(limit=limit)
    return [classifier.batch_to_dict(b) for b in batches]


@router.get("/classify-batch/{batch_id}")
async def get_classify_batch(
    batch_id: int,
    classifier: PublicationBatchClassifier = Depends(_get_batch_classifier),
    _=Depends(auth_security.get_current_user),
):
    """Retorna o estado atual de um batch (local cache)."""
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")
    return classifier.batch_to_dict(batch)


@router.post("/classify-batch/{batch_id}/refresh")
async def refresh_classify_batch(
    batch_id: int,
    classifier: PublicationBatchClassifier = Depends(_get_batch_classifier),
    _=Depends(auth_security.get_current_user),
):
    """
    Consulta a Anthropic para atualizar o status do batch.
    Retorna os contadores atualizados sem baixar os resultados.
    """
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")
    try:
        batch = await classifier.refresh_batch_status(batch)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar status: {exc}")
    return classifier.batch_to_dict(batch)


@router.post("/classify-batch/{batch_id}/apply")
async def apply_classify_batch(
    batch_id: int,
    background_tasks: BackgroundTasks,
    classifier: PublicationBatchClassifier = Depends(_get_batch_classifier),
    _=Depends(auth_security.get_current_user),
):
    """
    Baixa os resultados de um batch PRONTO e aplica as classificações
    nos PublicationRecord correspondentes.

    Esta operação pode levar algum tempo (dependendo do tamanho do batch),
    então roda em background.
    """
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")

    import logging as _logging
    _logger = _logging.getLogger(__name__)

    async def _run():
        try:
            # Garante status atualizado antes de baixar
            refreshed = await classifier.refresh_batch_status(batch)
            if not refreshed.results_url:
                _logger.info(
                    "Batch %s ainda não finalizado (status=%s). Pulando.",
                    batch_id, refreshed.anthropic_status,
                )
                return
            await classifier.apply_batch_results(refreshed)
        except Exception as exc:
            _logger.error("Erro ao aplicar batch %s: %s", batch_id, exc)

    background_tasks.add_task(_run)
    return {
        "message": "Aplicação do batch iniciada em background.",
        "batch_id": batch_id,
    }


@router.post("/classify-batch/{batch_id}/retry-errors")
async def retry_batch_errors(
    batch_id: int,
    classifier: PublicationBatchClassifier = Depends(_get_batch_classifier),
    current_user=Depends(auth_security.get_current_user),
):
    """
    Reprocessa os itens que falharam em um batch anterior.
    Coleta registros com erro, reseta status para NOVO, e envia novo batch.
    """
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")
    # Aceita retry se há error_details OU se errored_count > 0
    # (batches antigos antes da coluna error_details existir também são válidos)
    has_errors = bool(batch.error_details) or (batch.errored_count or 0) > 0
    if not has_errors:
        raise HTTPException(status_code=400, detail="Nenhum erro registrado neste batch.")

    records = classifier.collect_errored_records_from_batch(batch)
    if not records:
        raise HTTPException(
            status_code=404,
            detail="Nenhum registro com erro encontrado para reprocessamento.",
        )

    try:
        email = current_user.email if hasattr(current_user, "email") else None
        new_batch = await classifier.submit_batch(
            records=records, requested_by_email=email
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao enviar retry batch: {exc}",
        )

    return {
        "message": f"Novo batch criado com {len(records)} registros que falharam.",
        "original_batch_id": batch_id,
        "new_batch": classifier.batch_to_dict(new_batch),
    }


@router.get("/classify-batch/{batch_id}/errors")
async def get_batch_errors(
    batch_id: int,
    classifier: PublicationBatchClassifier = Depends(_get_batch_classifier),
    _=Depends(auth_security.get_current_user),
):
    """Retorna detalhes dos erros de um batch específico."""
    batch = classifier.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado.")
    return {
        "batch_id": batch_id,
        "errored_count": batch.errored_count or 0,
        "expired_count": batch.expired_count or 0,
        "error_details": batch.error_details or {},
    }


@router.get("/searches")
async def list_searches(
    limit: int = Query(20, ge=1, le=100),
    service: PublicationSearchService = Depends(_get_service),
):
    """Lista buscas anteriores."""
    return service.list_searches(limit=limit)


@router.get("/searches/{search_id}")
async def get_search(
    search_id: int,
    service: PublicationSearchService = Depends(_get_service),
):
    """Retorna detalhe de uma busca."""
    try:
        return service.get_search(search_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/searches/{search_id}/cancel")
async def cancel_search(
    search_id: int,
    service: PublicationSearchService = Depends(_get_service),
):
    """Cancela uma busca em andamento."""
    cancelled = service.cancel_search(search_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="Busca não pode ser cancelada.")
    return {"search_id": search_id, "status": "CANCELADO"}


# ─── Registros de Publicações ───────────────────

@router.get("/records")
async def list_records(
    search_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    linked_office_id: Optional[int] = Query(None, description="Filtra por escritório responsável"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: PublicationSearchService = Depends(_get_service),
):
    """Lista registros de publicações com filtros."""
    return service.list_records(
        search_id=search_id,
        status=status,
        linked_office_id=linked_office_id,
        limit=limit,
        offset=offset,
    )


@router.get("/records/grouped")
async def list_records_grouped(
    search_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    linked_office_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None, description="Data início (YYYY-MM-DD). Filtra por creation_date (data do Ajus)."),
    date_to: Optional[str] = Query(None, description="Data fim (YYYY-MM-DD). Filtra por creation_date (data do Ajus)."),
    category: Optional[str] = Query(None, description="Filtra por categoria de classificação."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: PublicationSearchService = Depends(_get_service),
):
    """Lista registros agrupados por processo (linked_lawsuit_id)."""
    return service.list_records_grouped(
        search_id=search_id,
        status=status,
        linked_office_id=linked_office_id,
        date_from=date_from,
        date_to=date_to,
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/records/grouped/export")
async def export_records_grouped(
    search_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    linked_office_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None, description="Data início (YYYY-MM-DD)."),
    date_to: Optional[str] = Query(None, description="Data fim (YYYY-MM-DD)."),
    category: Optional[str] = Query(None, description="Classificação primária."),
    db: Session = Depends(get_db),
):
    """
    Exporta as publicações (respeitando os filtros aplicados na tela de
    Processos com Publicações) em um arquivo XLSX. O arquivo tem uma linha
    por publicação, mantém a ordem da tela (CNJ, data de publicação desc) e
    inclui uma aba "Filtros" com os parâmetros usados.
    """
    content, filename = export_records_grouped_xlsx(
        db=db,
        search_id=search_id,
        status=status,
        linked_office_id=linked_office_id,
        date_from=date_from,
        date_to=date_to,
        category=category,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/lookup-by-cnj")
async def lookup_by_cnj(
    cnj: str = Query(..., description="Número CNJ do processo (com ou sem formatação)."),
    service: PublicationSearchService = Depends(_get_service),
):
    """
    Diagnóstico por processo: retorna tudo que o sistema conhece sobre o CNJ
    informado — buscas que o alcançaram, publicações encontradas, classificação
    atribuída, status atual e estado na fila de tratamento (RPA).
    """
    try:
        return service.lookup_by_cnj(cnj)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/records/duplicate-divergences")
async def list_duplicate_divergences(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: PublicationSearchService = Depends(_get_service),
):
    """
    Retorna duplicatas cujo texto difere do original.
    Útil para verificar se a deduplicação está descartando textos diferentes.
    """
    return service.list_duplicate_divergences(limit=limit, offset=offset)


@router.get("/records/{record_id}")
async def get_record(
    record_id: int,
    service: PublicationSearchService = Depends(_get_service),
):
    """Retorna detalhe completo de um registro."""
    try:
        return service.get_record(record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/records/{record_id}")
async def update_record_status(
    record_id: int,
    payload: UpdateRecordStatusRequest,
    service: PublicationSearchService = Depends(_get_service),
):
    """Atualiza o status de um registro de publicação."""
    try:
        return service.update_record_status(record_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/records/reclassify")
async def reclassify_records(
    payload: ReclassifyRecordsRequest,
    service: PublicationSearchService = Depends(_get_service),
    _=Depends(auth_security.get_current_user),
):
    """
    Aplica uma classificação manual a um conjunto de registros e reconstrói
    suas propostas de tarefa. Usado pelo operador quando a classificação
    automática precisa ser corrigida.
    """
    try:
        return service.reclassify_records(
            record_ids=payload.record_ids,
            category=payload.category,
            subcategory=payload.subcategory,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─── Agendamento por grupo (processo) ───────────

@router.post("/groups/{lawsuit_id}/schedule")
async def schedule_group(
    lawsuit_id: int,
    payload: ScheduleGroupRequest,
    service: PublicationSearchService = Depends(_get_service),
):
    """Agenda uma tarefa consolidada para todas as publicações de um processo."""
    try:
        result = service.schedule_group(
            lawsuit_id=lawsuit_id,
            payload_override=payload.payload_override,
            payload_overrides=payload.payload_overrides,
        )
        # Alias for frontend
        result["task_id"] = result.get("created_task_id")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao agendar: {exc}")


@router.post("/groups/records/schedule")
async def schedule_records(
    payload: ScheduleRecordsRequest,
    service: PublicationSearchService = Depends(_get_service),
):
    """
    Agenda uma tarefa para publicações SEM processo vinculado.
    Usa templates globais (office_external_id IS NULL).
    """
    try:
        result = service.schedule_records(
            record_ids=payload.record_ids,
            payload_override=payload.payload_override,
            payload_overrides=payload.payload_overrides,
        )
        result["task_id"] = result.get("created_task_id")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao agendar: {exc}")


# ─── Debug ──────────────────────────────────────

@router.get("/debug-api")
async def debug_legalone_api(
    query: str = Query(default="", description="Query string OData manual, ex: $filter=originType eq 'OfficialJournalsCrawler'&$top=2"),
    client: LegalOneApiClient = Depends(get_api_client),
    _=Depends(auth_security.get_current_user),
):
    """
    Chama diretamente a API do LegalOne (/Updates) com a query string fornecida
    e retorna a resposta raw (status + body). Útil para diagnosticar erros 400.
    """
    base_url = client.base_url
    if query:
        url = f"{base_url}/Updates?{query}"
    else:
        url = f"{base_url}/Updates?$top=1"

    client._refresh_token_if_needed()
    headers = {"Authorization": f"Bearer {client._Auth.token}"}

    try:
        resp = client._session.get(url, headers=headers, timeout=30)
        return {
            "status_code": resp.status_code,
            "url_called": url,
            "response_body": resp.text[:4000],
        }
    except Exception as exc:
        return {"error": str(exc), "url_called": url}


# ─── Classificações por Escritório (Overrides) ─────────────


class OverrideCreate(BaseModel):
    office_external_id: int
    category: str
    subcategory: str | None = None
    action: str = "exclude"  # "exclude" | "include_custom"
    custom_description: str | None = None


class OverrideUpdate(BaseModel):
    is_active: bool | None = None
    custom_description: str | None = None


class OverrideBulkRequest(BaseModel):
    category: str
    subcategory: str | None = None
    action: str = "exclude"  # "exclude" | "include_custom"
    custom_description: str | None = None
    # Se vazio/None, aplica a TODOS os escritórios conhecidos.
    office_external_ids: list[int] | None = None


@router.get("/classification-overrides")
async def list_classification_overrides(
    office_external_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _=Depends(auth_security.get_current_user),
):
    """Lista overrides de classificação. Filtra por escritório se informado."""
    from app.models.office_classification import OfficeClassificationOverride

    query = db.query(OfficeClassificationOverride)
    if office_external_id is not None:
        query = query.filter(
            OfficeClassificationOverride.office_external_id == office_external_id
        )
    overrides = query.order_by(
        OfficeClassificationOverride.office_external_id,
        OfficeClassificationOverride.category,
    ).all()
    return [
        {
            "id": o.id,
            "office_external_id": o.office_external_id,
            "category": o.category,
            "subcategory": o.subcategory,
            "action": o.action,
            "custom_description": o.custom_description,
            "is_active": o.is_active,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in overrides
    ]


@router.post("/classification-overrides")
async def create_classification_override(
    body: OverrideCreate,
    db: Session = Depends(get_db),
    _=Depends(auth_security.get_current_user),
):
    """Cria um override de classificação para um escritório."""
    from app.models.office_classification import OfficeClassificationOverride

    if body.action not in ("exclude", "include_custom"):
        raise HTTPException(400, "action deve ser 'exclude' ou 'include_custom'")

    existing = (
        db.query(OfficeClassificationOverride)
        .filter(
            OfficeClassificationOverride.office_external_id == body.office_external_id,
            OfficeClassificationOverride.category == body.category,
            OfficeClassificationOverride.subcategory == body.subcategory,
            OfficeClassificationOverride.action == body.action,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Override já existe para esta combinação.")

    override = OfficeClassificationOverride(
        office_external_id=body.office_external_id,
        category=body.category,
        subcategory=body.subcategory,
        action=body.action,
        custom_description=body.custom_description,
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    return {
        "id": override.id,
        "office_external_id": override.office_external_id,
        "category": override.category,
        "subcategory": override.subcategory,
        "action": override.action,
        "is_active": override.is_active,
    }


@router.patch("/classification-overrides/{override_id}")
async def update_classification_override(
    override_id: int,
    body: OverrideUpdate,
    db: Session = Depends(get_db),
    _=Depends(auth_security.get_current_user),
):
    """Atualiza um override (ativa/desativa ou altera descrição)."""
    from app.models.office_classification import OfficeClassificationOverride

    override = db.query(OfficeClassificationOverride).filter_by(id=override_id).first()
    if not override:
        raise HTTPException(404, "Override não encontrado.")
    if body.is_active is not None:
        override.is_active = body.is_active
    if body.custom_description is not None:
        override.custom_description = body.custom_description
    db.commit()
    return {"ok": True, "id": override.id, "is_active": override.is_active}


@router.delete("/classification-overrides/{override_id}")
async def delete_classification_override(
    override_id: int,
    db: Session = Depends(get_db),
    _=Depends(auth_security.get_current_user),
):
    """Remove um override de classificação."""
    from app.models.office_classification import OfficeClassificationOverride

    override = db.query(OfficeClassificationOverride).filter_by(id=override_id).first()
    if not override:
        raise HTTPException(404, "Override não encontrado.")
    db.delete(override)
    db.commit()
    return {"ok": True}


@router.post("/classification-overrides/bulk")
async def bulk_create_classification_overrides(
    body: OverrideBulkRequest,
    db: Session = Depends(get_db),
    _=Depends(auth_security.get_current_user),
):
    """
    Aplica o mesmo override a múltiplos escritórios (ou a TODOS, se
    `office_external_ids` for omitido/vazio). Ignora silenciosamente
    escritórios que já possuem a combinação (category/subcategory/action).
    """
    from app.models.office_classification import OfficeClassificationOverride
    from app.models.legal_one import LegalOneOffice

    if body.action not in ("exclude", "include_custom"):
        raise HTTPException(400, "action deve ser 'exclude' ou 'include_custom'")

    target_ids = body.office_external_ids
    if not target_ids:
        target_ids = [
            o.external_id for o in db.query(LegalOneOffice).all() if o.external_id is not None
        ]

    if not target_ids:
        raise HTTPException(400, "Nenhum escritório disponível para aplicar o override.")

    created = 0
    skipped = 0
    for office_id in target_ids:
        existing = (
            db.query(OfficeClassificationOverride)
            .filter(
                OfficeClassificationOverride.office_external_id == office_id,
                OfficeClassificationOverride.category == body.category,
                OfficeClassificationOverride.subcategory == body.subcategory,
                OfficeClassificationOverride.action == body.action,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue
        db.add(
            OfficeClassificationOverride(
                office_external_id=office_id,
                category=body.category,
                subcategory=body.subcategory,
                action=body.action,
                custom_description=body.custom_description,
            )
        )
        created += 1
    db.commit()
    return {
        "created": created,
        "skipped_existing": skipped,
        "total_offices": len(target_ids),
    }


@router.delete("/classification-overrides/bulk")
async def bulk_delete_classification_overrides(
    category: str = Query(...),
    subcategory: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _=Depends(auth_security.get_current_user),
):
    """
    Remove overrides que batem (category + subcategory opcional + action opcional)
    de TODOS os escritórios de uma vez.
    """
    from app.models.office_classification import OfficeClassificationOverride

    q = db.query(OfficeClassificationOverride).filter(
        OfficeClassificationOverride.category == category,
    )
    if subcategory is None:
        q = q.filter(OfficeClassificationOverride.subcategory.is_(None))
    else:
        q = q.filter(OfficeClassificationOverride.subcategory == subcategory)
    if action:
        q = q.filter(OfficeClassificationOverride.action == action)

    count = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.get("/classification-taxonomy")
async def get_classification_taxonomy(
    office_external_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _=Depends(auth_security.get_current_user),
):
    """
    Retorna a taxonomia de classificações.
    Se office_external_id for informado, aplica os overrides do escritório.
    """
    from app.services.classifier.taxonomy import CLASSIFICATION_TREE, build_taxonomy_text
    from app.services.classifier.prompts import load_office_overrides

    if office_external_id:
        excluded, custom = load_office_overrides(db, office_external_id)
        # Build custom tree for response
        tree = {k: list(v) for k, v in CLASSIFICATION_TREE.items()}
        if excluded:
            cats_to_remove = set()
            for cat, sub in excluded:
                if sub is None:
                    cats_to_remove.add(cat)
                elif cat in tree and sub in tree[cat]:
                    tree[cat].remove(sub)
            for cat in cats_to_remove:
                tree.pop(cat, None)
        if custom:
            for item in custom:
                cat = item.get("category", "")
                sub = item.get("subcategory")
                if cat not in tree:
                    tree[cat] = []
                if sub and sub not in tree[cat]:
                    tree[cat].append(sub)
        return {"office_external_id": office_external_id, "taxonomy": tree}

    return {"office_external_id": None, "taxonomy": CLASSIFICATION_TREE}

