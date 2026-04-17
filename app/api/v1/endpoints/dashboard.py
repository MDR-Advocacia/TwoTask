# app/api/v1/endpoints/dashboard.py

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_db
# Importar os modelos existentes
from app.models import canonical as canonical_models
from app.models import rules as rules_models
# Adicionar import do novo modelo de log
from app.models.batch_execution import BatchExecution
from app.models.publication_search import (
    PublicationRecord,
    RECORD_STATUS_NEW,
    RECORD_STATUS_CLASSIFIED,
    RECORD_STATUS_SCHEDULED,
    RECORD_STATUS_IGNORED,
    RECORD_STATUS_ERROR,
)
from app.api.v1 import schemas

router = APIRouter()

# Status que contam como "tratadas" (ação do operador, seja agendar ou dar ciência)
_TREATED_STATUSES = (
    RECORD_STATUS_CLASSIFIED,
    RECORD_STATUS_SCHEDULED,
    RECORD_STATUS_IGNORED,
)

# --- SEUS ENDPOINTS EXISTENTES (INALTERADOS) ---

@router.get("/task_templates", response_model=List[schemas.TaskTemplate])
def get_task_templates(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os templates de tarefas canônicos.
    """
    templates = db.query(canonical_models.CanonicalTaskTemplate).all()
    if not templates:
        raise HTTPException(status_code=404, detail="Nenhum template de tarefa encontrado.")
    return templates

@router.get("/squads", response_model=List[schemas.Squad])
def get_squads(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os squads e membros ATIVOS a partir dos
    dados sincronizados (tabelas de 'rules').
    """
    squads = (
        db.query(rules_models.Squad)
        .filter(rules_models.Squad.is_active == True)
        .options(
            joinedload(rules_models.Squad.members)
        )
        .all()
    )
    
    if not squads:
        raise HTTPException(status_code=404, detail="Nenhum squad ativo encontrado.")
        
    active_squads = []
    for squad in squads:
        squad_data = schemas.Squad.from_orm(squad)
        # Filtra manualmente para garantir que apenas membros ativos sejam incluídos
        squad_data.members = [member for member in squad.members if hasattr(member, 'is_active') and member.is_active]
        active_squads.append(squad_data)

    return active_squads

# --- NOSSO NOVO ENDPOINT ADICIONADO AQUI ---

@router.get(
    "/batch-executions",
    response_model=List[schemas.BatchExecutionResponse],
    summary="Obtém o histórico das últimas execuções de tarefas em lote"
)
def get_batch_executions(
    db: Session = Depends(get_db),
    limit: int = 200
):
    """
    Retorna uma lista das últimas N execuções de lote processadas pela API,
    com os detalhes de cada item (sucesso ou falha).
    
    - **limit**: Número de execuções a serem retornadas (padrão: 20).
    """
    executions = (
        db.query(BatchExecution)
        .options(joinedload(BatchExecution.items)) # Otimiza a query para carregar os itens juntos
        .order_by(BatchExecution.start_time.desc())
        .limit(limit)
        .all()
    )
    return executions


# ──────────────────────────────────────────────────────────────
# Visão geral para o dashboard inicial (KPIs + funil + série)
# ──────────────────────────────────────────────────────────────

@router.get(
    "/publications-overview",
    summary="KPIs, funil de status e série diária de publicações para o dashboard",
)
def get_publications_overview(
    days: int = Query(14, ge=7, le=60, description="Janela da série diária em dias."),
    db: Session = Depends(get_db),
):
    """
    Retorna num único payload tudo que o dashboard precisa:
      - kpis: pendentes (NOVO agora), tratadas/agendadas na janela,
        recebidas na janela e taxa de erro da janela (%)
      - funnel: contagem atual por status (snapshot)
      - timeseries: por dia [{date, recebidas, tratadas}] últimos `days` dias
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    base = db.query(PublicationRecord).filter(PublicationRecord.is_duplicate == False)

    # --- Funil atual (snapshot por status) ------------------------------------
    status_rows = (
        base.with_entities(
            PublicationRecord.status,
            sa_func.count(PublicationRecord.id),
        )
        .group_by(PublicationRecord.status)
        .all()
    )
    by_status = {row[0]: int(row[1]) for row in status_rows}

    funnel = {
        "novo": by_status.get(RECORD_STATUS_NEW, 0),
        "classificado": by_status.get(RECORD_STATUS_CLASSIFIED, 0),
        "agendado": by_status.get(RECORD_STATUS_SCHEDULED, 0),
        "ignorado": by_status.get(RECORD_STATUS_IGNORED, 0),
        "erro": by_status.get(RECORD_STATUS_ERROR, 0),
    }

    # --- KPIs da janela -------------------------------------------------------
    pendentes_agora = funnel["novo"]

    treated_in_window = (
        base.filter(PublicationRecord.updated_at >= window_start)
        .filter(PublicationRecord.status.in_(_TREATED_STATUSES))
        .count()
    )
    scheduled_in_window = (
        base.filter(PublicationRecord.updated_at >= window_start)
        .filter(PublicationRecord.status == RECORD_STATUS_SCHEDULED)
        .count()
    )
    received_in_window = (
        base.filter(PublicationRecord.created_at >= window_start).count()
    )
    errors_in_window = (
        base.filter(PublicationRecord.created_at >= window_start)
        .filter(PublicationRecord.status == RECORD_STATUS_ERROR)
        .count()
    )
    error_rate = (
        round((errors_in_window / received_in_window) * 100, 1)
        if received_in_window > 0
        else 0.0
    )

    kpis = {
        "pendentes_agora": pendentes_agora,
        "tratadas_janela": treated_in_window,
        "agendadas_janela": scheduled_in_window,
        "recebidas_janela": received_in_window,
        "taxa_erro_pct": error_rate,
        "window_days": days,
    }

    # --- Série diária (recebidas vs tratadas) --------------------------------
    # Agrupa por data (UTC). Frontend formata em pt-BR.
    received_by_day_rows = (
        base.with_entities(
            sa_func.date(PublicationRecord.created_at).label("d"),
            sa_func.count(PublicationRecord.id),
        )
        .filter(PublicationRecord.created_at >= window_start)
        .group_by(sa_func.date(PublicationRecord.created_at))
        .all()
    )
    treated_by_day_rows = (
        base.with_entities(
            sa_func.date(PublicationRecord.updated_at).label("d"),
            sa_func.count(PublicationRecord.id),
        )
        .filter(PublicationRecord.updated_at >= window_start)
        .filter(PublicationRecord.status.in_(_TREATED_STATUSES))
        .group_by(sa_func.date(PublicationRecord.updated_at))
        .all()
    )

    received_map = {str(r[0]): int(r[1]) for r in received_by_day_rows}
    treated_map = {str(r[0]): int(r[1]) for r in treated_by_day_rows}

    timeseries: list[dict] = []
    for i in range(days):
        day = (now - timedelta(days=days - 1 - i)).date()
        key = str(day)
        timeseries.append(
            {
                "date": key,
                "recebidas": received_map.get(key, 0),
                "tratadas": treated_map.get(key, 0),
            }
        )

    return {
        "kpis": kpis,
        "funnel": funnel,
        "timeseries": timeseries,
        "generated_at": now.isoformat(),
    }