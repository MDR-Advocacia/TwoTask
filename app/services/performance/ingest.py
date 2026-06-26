"""Ingestão incremental das tarefas do L1 (API /Tasks) → perf_l1_tarefa.

Substitui o seed estático do export pela ATUALIZAÇÃO VIVA: puxa as tarefas
CONCLUÍDAS do escritório desde uma data (effectiveEndDateTime) e faz upsert por
l1_task_id, resolvendo subtipo (catálogo legal_one_task_subtypes) e executor
(finishedBy → legal_one_users → perf_pessoa por nome sem acento).

Mapeamento API → schema:
  effectiveEndDateTime → concluido_em ; creationDate → cadastrado_em ;
  endDateTime → prazo_previsto ; finishedBy → cumprido_por/pessoa ;
  subTypeId → subtipo ; status = 'Cumprido' (tem finishedBy).

Escopo = só as pessoas do roster (perf_pessoa), igual ao seed.
Pendentes (backlog) dependem do responsável via participants — fase seguinte.
"""

import datetime
import logging
import unicodedata

from app.models.legal_one import LegalOneTaskSubType, LegalOneUser
from app.models.performance import PerfPessoa, PerfTarefa
from app.services.legal_one_client import LegalOneApiClient

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    _BRT = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover
    _BRT = None

_SELECT = (
    "id,statusId,typeId,subTypeId,responsibleOfficeId,creationDate,"
    "endDateTime,effectiveEndDateTime,finishedBy"
)


def _norm(s) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.strip().lower().split())


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def ingest_completed(db, office_external_id: int, since, client: LegalOneApiClient | None = None) -> dict:
    """Puxa as tarefas concluídas do escritório desde `since` e faz upsert."""
    client = client or LegalOneApiClient()
    sub_map = {s.external_id: s.name for s in db.query(LegalOneTaskSubType).all()}
    user_map = {u.external_id: u.name for u in db.query(LegalOneUser).all()}
    pessoa_map = {p.nome_norm: p.id for p in db.query(PerfPessoa).all()}

    if isinstance(since, datetime.datetime):
        since_iso = since.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        since_iso = str(since)

    flt = (
        f"responsibleOfficeId eq {int(office_external_id)} "
        f"and effectiveEndDateTime ge {since_iso}"
    )
    tasks = client.search_tasks(
        filter_expression=flt, top=30, orderby="effectiveEndDateTime desc", select=_SELECT
    )

    ins = upd = fora = 0
    for t in tasks:
        fb = t.get("finishedBy")
        nome = user_map.get(fb) if fb else None
        pid = pessoa_map.get(_norm(nome)) if nome else None
        if not pid:
            fora += 1
            continue
        l1id = t.get("id")
        vals = dict(
            pessoa_id=pid,
            cumprido_por_nome=nome,
            subtipo=sub_map.get(t.get("subTypeId")),
            status="Cumprido",
            concluido_em=_parse_dt(t.get("effectiveEndDateTime")),
            cadastrado_em=_parse_dt(t.get("creationDate")),
            prazo_previsto=_parse_dt(t.get("endDateTime")),
        )
        existing = db.query(PerfTarefa).filter(PerfTarefa.l1_task_id == l1id).first() if l1id else None
        if existing:
            for k, v in vals.items():
                setattr(existing, k, v)
            upd += 1
        else:
            db.add(PerfTarefa(l1_task_id=l1id, **vals))
            ins += 1
    db.commit()
    return {
        "total_api": len(tasks),
        "inseridas": ins,
        "atualizadas": upd,
        "fora_do_roster": fora,
    }
