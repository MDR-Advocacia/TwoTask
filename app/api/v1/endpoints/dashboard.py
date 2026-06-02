# app/api/v1/endpoints/dashboard.py

from datetime import datetime, timedelta, timezone
from typing import List, Literal

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
from app.models.publication_treatment import (
    PublicationTreatmentItem,
    QUEUE_STATUS_PENDING,
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
    granularity: Literal["day", "hour"] = Query(
        "day",
        description="Granularidade da série: 'day' (últimos N dias) ou 'hour' (últimas 24h).",
    ),
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

    # --- Série temporal (recebidas vs tratadas) ------------------------------
    # granularity="day": N dias agrupados por data (comportamento original).
    # granularity="hour": últimas 24h agrupadas por hora. Pra hora, agrupamos
    # no Python (janela pequena) carimbando em UTC — evita o atrito de timezone
    # do date_trunc no servidor e mantém a chave alinhada com os buckets gerados.
    timeseries: list[dict] = []

    if granularity == "hour":
        series_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(
            hours=23
        )
        received_ts = [
            r[0]
            for r in base.with_entities(PublicationRecord.created_at)
            .filter(PublicationRecord.created_at >= series_start)
            .all()
        ]
        treated_ts = [
            r[0]
            for r in base.with_entities(PublicationRecord.updated_at)
            .filter(PublicationRecord.updated_at >= series_start)
            .filter(PublicationRecord.status.in_(_TREATED_STATUSES))
            .all()
        ]

        def _bucket_by_hour(ts_list):
            buckets: dict[str, int] = {}
            for ts in ts_list:
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                key = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
                buckets[key] = buckets.get(key, 0) + 1
            return buckets

        received_map = _bucket_by_hour(received_ts)
        treated_map = _bucket_by_hour(treated_ts)

        for i in range(24):
            h = series_start + timedelta(hours=i)
            key = h.strftime("%Y-%m-%dT%H")
            timeseries.append(
                {
                    "date": h.isoformat(),
                    "recebidas": received_map.get(key, 0),
                    "tratadas": treated_map.get(key, 0),
                }
            )
    else:
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
        "granularity": granularity,
        "generated_at": now.isoformat(),
    }


# ───────────────────────────────────────────────────────────────
# Pulso operacional (ritmo / backlog / projeção) — Bloco 1 do dashboard
# ───────────────────────────────────────────────────────────────

@router.get(
    "/publications-rhythm",
    summary="Pulso operacional: ritmo, backlog, projeção e tempo médio de tratamento",
)
def get_publications_rhythm(db: Session = Depends(get_db)):
    """
    Retorna o "pulso" do tratamento de publicações pro Bloco 1 do dashboard:
      - backlog atual (status NOVO) e idade da publicação mais antiga na fila
      - ritmo da última hora vs média/hora dos últimos 7 dias
      - taxa de chegada e projeção de quando o backlog zera (burndown)
      - tempo médio de tratamento (criação -> status terminal) nos últimos 7d
      - tratadas hoje

    Critério de "tratada": registro não-duplicado com status terminal
    (CLASSIFICADO/AGENDADO/IGNORADO) cujo updated_at caiu na janela — o MESMO
    critério do publications-overview, pra os dois números baterem. Inclui a
    classificação automática da IA (pulso agregado de throughput); o placar
    individual por operador (gamificação) é uma métrica à parte, baseada na
    autoria scheduled_by_*/ignored_by_*.
    """
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    seven_days_ago = now - timedelta(days=7)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    base = db.query(PublicationRecord).filter(PublicationRecord.is_duplicate == False)

    def _treated_since(since: datetime) -> int:
        return (
            base.filter(PublicationRecord.updated_at >= since)
            .filter(PublicationRecord.status.in_(_TREATED_STATUSES))
            .count()
        )

    # Backlog atual (NOVO) + idade da mais antiga na fila.
    backlog = base.filter(PublicationRecord.status == RECORD_STATUS_NEW).count()
    oldest_dt = (
        base.filter(PublicationRecord.status == RECORD_STATUS_NEW)
        .with_entities(sa_func.min(PublicationRecord.created_at))
        .scalar()
    )
    oldest_age_minutes = (
        int((now - oldest_dt).total_seconds() // 60) if oldest_dt else None
    )

    # Ritmo da última hora vs média/hora dos últimos 7 dias.
    last_hour_treated = _treated_since(one_hour_ago)
    last_7d_treated = _treated_since(seven_days_ago)
    avg_per_hour_7d = round(last_7d_treated / (7 * 24), 1)
    vs_avg_pct = (
        round((last_hour_treated - avg_per_hour_7d) / avg_per_hour_7d * 100, 1)
        if avg_per_hour_7d > 0
        else 0.0
    )

    treated_today = _treated_since(today_start)

    # Chegada na última hora -> taxa líquida -> projeção de burndown.
    arrivals_last_hour = base.filter(
        PublicationRecord.created_at >= one_hour_ago
    ).count()
    net_rate_per_hour = last_hour_treated - arrivals_last_hour
    if backlog == 0:
        burndown_label = "Backlog zerado"
    elif net_rate_per_hour > 0:
        minutes = int(backlog / net_rate_per_hour * 60)
        h, m = divmod(minutes, 60)
        burndown_label = (
            f"No ritmo atual, backlog zera em ~{h}h{m:02d}min"
            if h
            else f"No ritmo atual, backlog zera em ~{m}min"
        )
    else:
        burndown_label = (
            f"Backlog crescendo ~{abs(net_rate_per_hour)}/h no ritmo atual"
        )

    # Tempo médio de tratamento (criação -> status terminal) nos últimos 7d.
    avg_handling_seconds = (
        base.filter(PublicationRecord.updated_at >= seven_days_ago)
        .filter(PublicationRecord.status.in_(_TREATED_STATUSES))
        .with_entities(
            sa_func.avg(
                sa_func.extract(
                    "epoch",
                    PublicationRecord.updated_at - PublicationRecord.created_at,
                )
            )
        )
        .scalar()
    )
    avg_handling_minutes = (
        int(avg_handling_seconds // 60) if avg_handling_seconds else None
    )

    return {
        "backlog": backlog,
        "oldest_pending_age_minutes": oldest_age_minutes,
        "last_hour_treated": last_hour_treated,
        "avg_per_hour_7d": avg_per_hour_7d,
        "vs_avg_pct": vs_avg_pct,
        "treated_today": treated_today,
        "arrivals_last_hour": arrivals_last_hour,
        "net_rate_per_hour": net_rate_per_hour,
        "burndown_label": burndown_label,
        "avg_handling_minutes": avg_handling_minutes,
        "generated_at": now.isoformat(),
    }


# ───────────────────────────────────────────────────────────────
# Pipeline de hoje (funil + próximas saídas da fila) — Bloco 3
# ───────────────────────────────────────────────────────────────

@router.get(
    "/publications-pipeline",
    summary="Funil de hoje + próximas saídas da fila de tratamento web",
)
def get_publications_pipeline(db: Session = Depends(get_db)):
    """
    Alimenta o Bloco 3 do dashboard:
      - funnel_today: recebidas / tratadas / agendadas hoje (publicacao_registros)
      - next_out: próximos itens PENDENTES na fila de tratamento web
        (publicacao_tratamento_itens), ordenados por chegada (FIFO) — é o que
        a próxima rodada do RPA vai processar
      - pending_total: total na fila pendente (pro "ver fila completa")
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    base = db.query(PublicationRecord).filter(PublicationRecord.is_duplicate == False)

    received_today = base.filter(PublicationRecord.created_at >= today_start).count()
    treated_today = (
        base.filter(PublicationRecord.updated_at >= today_start)
        .filter(PublicationRecord.status.in_(_TREATED_STATUSES))
        .count()
    )
    scheduled_today = base.filter(
        PublicationRecord.scheduled_at >= today_start
    ).count()

    pending_q = db.query(PublicationTreatmentItem).filter(
        PublicationTreatmentItem.queue_status == QUEUE_STATUS_PENDING
    )
    pending_total = pending_q.count()
    next_out = (
        pending_q.order_by(PublicationTreatmentItem.created_at.asc()).limit(10).all()
    )

    return {
        "funnel_today": {
            "received": received_today,
            "treated": treated_today,
            "scheduled": scheduled_today,
        },
        "next_out": [
            {
                "id": item.id,
                "cnj": item.linked_lawsuit_cnj,
                "target_status": item.target_status,
                "queued_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in next_out
        ],
        "pending_total": pending_total,
        "generated_at": now.isoformat(),
    }
