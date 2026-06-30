"""Cancelamento em lote de tarefas duplicadas do board (fase B) — LIVE + BATCH.

Fluxo do job (2 fases, em THREAD daemon, progresso persistido em perf_cancel_job
pro polling funcionar com vários workers):

  ① VARREDURA LIVE — pra cada processo-candidato (snapshot só escopa), resolve o
     lawsuit e busca AO VIVO as pendentes reais do subtipo (`find_tasks_for_lawsuit`),
     mantém a mais antiga e monta a lista real a cancelar. Não depende da frescura
     do snapshot (duplicada já resolvida não entra).

  ② CANCELAMENTO EM LOTE — em vez de 1 POST+verify por tarefa (~3s/tarefa), faz:
     pré-check de status EM LOTE (chunks de 28 via OR filter — preserva terminais,
     nunca toca Cumprida) → POST EM LOTE (N ids num request, doc §5) → espera o
     backend assíncrono do L1 → verify EM LOTE (statusId via API), com 1 retry pros
     que não refletiram. Corta de ~minutos pra ~dezenas de segundos.

Suporta abort (status 'aborting', checado entre etapas).
"""

import logging
import threading
import time
import uuid

from sqlalchemy import func, text

from app.db.session import SessionLocal
from app.models.performance import PerfCancelJob

logger = logging.getLogger(__name__)

_MAX = 5000  # trava de segurança por lote
_TERMINAL = {1, 2, 3}  # Cumprido / Não cumprido / Cancelado — nunca cancelar
_TARGET = 3  # Cancelado
_POST_CHUNK = 50  # ids por POST em lote
_FETCH_CHUNK = 28  # ids por GET de status (OR filter; /Tasks tem $top=30)


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def iniciar(team: str, subtipo: str) -> str:
    """Cria o job (fase scanning), dispara a thread e devolve o job_id."""
    job_id = uuid.uuid4().hex[:12]
    db = SessionLocal()
    try:
        db.add(
            PerfCancelJob(id=job_id, team=team, subtipo=subtipo, status="running", fase="scanning", erros=[])
        )
        db.commit()
    finally:
        db.close()
    threading.Thread(target=_run, args=(job_id, team, subtipo), daemon=True).start()
    return job_id


def solicitar_abort(job_id: str) -> bool:
    """Pede pra thread parar — ela checa entre etapas e encerra."""
    db = SessionLocal()
    try:
        j = db.get(PerfCancelJob, job_id)
        if not j or j.status == "done":
            return False
        j.status = "aborting"
        db.commit()
        return True
    finally:
        db.close()


def _abortado(db, job_id: str) -> bool:
    return db.execute(
        text("SELECT status FROM perf_cancel_job WHERE id = :id"), {"id": job_id}
    ).scalar() == "aborting"


def _statuses(c, ids: list) -> dict:
    """statusId atual de N tarefas, EM LOTE (chunks de 28 via OR filter na API)."""
    out: dict = {}
    for i in range(0, len(ids), _FETCH_CHUNK):
        chunk = ids[i : i + _FETCH_CHUNK]
        flt = " or ".join(f"id eq {int(x)}" for x in chunk)
        try:
            for r in c.search_tasks(filter_expression=flt, select="id,statusId", top=30):
                out[int(r["id"])] = _to_int(r.get("statusId"))
        except Exception:  # noqa: BLE001
            logger.exception("busca de status em lote falhou (offset %s)", i)
    return out


def _scan_live(db, job, team: str, subtipo: str, c) -> list:
    """Varre o L1 ao vivo e devolve os task_ids reais a cancelar (mantém a mais
    antiga por processo). Atualiza scan_feito/scan_total no job."""
    sample = db.execute(
        text("SELECT l1_task_id FROM perf_l1_tarefa WHERE subtipo = :s AND l1_task_id IS NOT NULL LIMIT 1"),
        {"s": subtipo},
    ).scalar()
    if not sample:
        return []
    subid = c.get_task_by_id(int(sample)).get("subTypeId")
    if not subid:
        return []
    cands = db.execute(
        text(
            """
            SELECT pasta, cnj FROM perf_l1_tarefa
            WHERE subtipo = :s AND status = 'Pendente' AND pasta IS NOT NULL AND l1_task_id IS NOT NULL
              AND pessoa_id IN (SELECT id FROM perf_pessoa WHERE equipe = :t)
            GROUP BY pasta, cnj HAVING count(*) > 1
            """
        ),
        {"s": subtipo, "t": team},
    ).fetchall()
    job.scan_total = len(cands)
    db.commit()

    task_ids: list = []
    for i, r in enumerate(cands):
        if _abortado(db, job.id):
            break
        try:
            lw = None
            if r.cnj:
                lw = c.search_lawsuit_by_cnj(r.cnj)
            if not lw and r.pasta:
                lw = c.search_lawsuit_by_folder(r.pasta)
            if lw:
                live = c.find_tasks_for_lawsuit(
                    int(lw["id"]), subtype_id=int(subid), status_ids=[0], top=30
                )
                live = sorted(live, key=lambda x: (x.get("creationDate") or "", x.get("id") or 0))
                if len(live) > 1:
                    task_ids.extend(int(t["id"]) for t in live[1:])  # mantém a mais antiga
        except Exception:  # noqa: BLE001
            logger.exception("scan live falhou na pasta %s", getattr(r, "pasta", "?"))
        job.scan_feito = i + 1
        db.commit()
    return task_ids[:_MAX]


def _cancel_batch(db, job, ids: list, c) -> None:
    """Cancela EM LOTE: pré-check de status (preserva terminais) → POST em lote →
    verify em lote, com 1 retry pros não confirmados."""
    from app.services.prazos_iniciais.legacy_task_http_cancellation_service import (
        LegacyTaskHttpCancellationService,
    )

    svc = LegacyTaskHttpCancellationService()

    # 1. pré-check em lote — só cancela status CONFIRMADO cancelável (0/4/5).
    # Terminal (1/2/3) ou status que o pré-check não conseguiu confirmar (None,
    # ex.: chunk perdido em 429) são pulados — NUNCA arrisca tocar Cumprida.
    st = _statuses(c, ids)
    alvo = [i for i in ids if st.get(i) in (0, 4, 5)]
    job.preservadas = (job.preservadas or 0) + (len(ids) - len(alvo))
    job.total = len(alvo)
    db.commit()
    if not alvo:
        job.feito = 0
        db.commit()
        return

    confirmados: set = set()
    pendentes = list(alvo)
    for rodada in range(2):  # POST + verify, com 1 retry pros que não refletiram
        if not pendentes or _abortado(db, job.id):
            break
        # POST em lotes de _POST_CHUNK
        for i in range(0, len(pendentes), _POST_CHUNK):
            if _abortado(db, job.id):
                break
            try:
                svc.post_cancel_batch(task_ids=pendentes[i : i + _POST_CHUNK], target_status_id=_TARGET)
            except Exception:  # noqa: BLE001
                logger.exception("POST batch falhou (rodada %s)", rodada)
        time.sleep(8 if rodada == 0 else 6)  # backend assíncrono do L1 reflete
        # verify em lote (atualiza progresso por chunk)
        for i in range(0, len(pendentes), _FETCH_CHUNK):
            if _abortado(db, job.id):
                break
            chunk = pendentes[i : i + _FETCH_CHUNK]
            ver = _statuses(c, chunk)
            confirmados.update(t for t in chunk if ver.get(t) == _TARGET)
            job.cancelled = len(confirmados)
            job.feito = len(confirmados)
            db.commit()
        pendentes = [t for t in pendentes if t not in confirmados]

    # Espelha no snapshot local: as confirmadas viram 'Cancelado' → somem de
    # pendente/atrasado no board (que lê do snapshot), deixando o gráfico coerente
    # com o que foi cancelado de verdade — sem esperar o próximo ingest.
    if confirmados:
        ids_sql = ",".join(str(int(t)) for t in confirmados)
        db.execute(
            text(f"UPDATE perf_l1_tarefa SET status = 'Cancelado' WHERE l1_task_id IN ({ids_sql})")
        )
        db.commit()

    job.falhas = (job.falhas or 0) + len(pendentes)
    job.feito = job.total
    db.commit()


def _run(job_id: str, team: str, subtipo: str) -> None:
    from app.services.legal_one_client import LegalOneApiClient

    db = SessionLocal()
    try:
        c = LegalOneApiClient()
        job = db.get(PerfCancelJob, job_id)

        # FASE 1 — varredura ao vivo
        ids = _scan_live(db, job, team, subtipo, c)
        job.total = len(ids)
        job.fase = "cancelling"
        db.commit()

        # FASE 2 — cancelamento em lote
        if ids and not _abortado(db, job_id):
            _cancel_batch(db, job, ids, c)

        job.status = "done"
        job.fase = "done"
        job.terminado_em = func.now()
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("job de cancelamento %s estourou", job_id)
        try:
            j = db.get(PerfCancelJob, job_id)
            if j:
                j.status = "done"
                j.fase = "done"
                j.terminado_em = func.now()
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def status(job_id: str) -> dict | None:
    db = SessionLocal()
    try:
        j = db.get(PerfCancelJob, job_id)
        if not j:
            return None
        return {
            "job_id": j.id,
            "status": j.status,
            "fase": j.fase,
            "scan_total": j.scan_total or 0,
            "scan_feito": j.scan_feito or 0,
            "total": j.total or 0,
            "feito": j.feito or 0,
            "cancelled": j.cancelled or 0,
            "preservadas": j.preservadas or 0,
            "falhas": j.falhas or 0,
            "erros": j.erros or [],
        }
    finally:
        db.close()
