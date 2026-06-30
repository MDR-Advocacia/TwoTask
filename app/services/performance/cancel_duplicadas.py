"""Cancelamento em lote de tarefas duplicadas do board (fase B) — LIVE.

Antes de cancelar, VARRE o L1 ao vivo: pra cada processo-candidato (vindo do
snapshot só pra escopar) busca as tarefas PENDENTES REAIS daquele subtipo agora
(`find_tasks_for_lawsuit`), mantém a mais antiga e marca as outras pra cancelar.
Assim não depende da frescura do snapshot — duplicada já resolvida não entra na
conta (era o que inflava as "preservadas").

Depois cancela via `LegacyTaskHttpCancellationService.cancel_task` (método B:
POST web + verify API; cobre Workflow; pré-check de terminal; idempotente).

Roda em THREAD daemon e grava o progresso (2 fases: scanning → cancelling) em
`perf_cancel_job`, pro polling funcionar com vários workers. Suporta abort
(status 'aborting', checado a cada item).
"""

import logging
import threading
import uuid

from sqlalchemy import func, text

from app.db.session import SessionLocal
from app.models.performance import PerfCancelJob

logger = logging.getLogger(__name__)

_MAX = 5000  # trava de segurança por lote


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
    """Pede pra thread parar — ela checa a cada item e encerra."""
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


def _scan_live(db, job, team: str, subtipo: str) -> list:
    """Varre o L1 ao vivo e devolve os task_ids reais a cancelar (mantém a mais
    antiga por processo). Atualiza scan_feito/scan_total no job."""
    from app.services.legal_one_client import LegalOneApiClient

    c = LegalOneApiClient()
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


def _run(job_id: str, team: str, subtipo: str) -> None:
    from app.services.prazos_iniciais.legacy_task_http_cancellation_service import (
        LegacyTaskHttpCancellationService,
    )

    db = SessionLocal()
    try:
        job = db.get(PerfCancelJob, job_id)

        # FASE 1 — varredura ao vivo
        ids = _scan_live(db, job, team, subtipo)
        job.total = len(ids)
        job.fase = "cancelling"
        db.commit()

        # FASE 2 — cancelamento (só dos ids reais)
        if not _abortado(db, job_id):
            svc = LegacyTaskHttpCancellationService()
            erros: list = []
            for tid in ids:
                if _abortado(db, job_id):
                    break
                reason = None
                try:
                    r = svc.cancel_task(task_id=tid)
                    reason = r.get("reason")
                except Exception as e:  # noqa: BLE001
                    logger.exception("cancelamento de duplicada (task %s) falhou", tid)
                    reason = f"exc: {e}"
                job.feito = (job.feito or 0) + 1
                if reason == "cancelled":
                    job.cancelled = (job.cancelled or 0) + 1
                elif reason in ("already_in_target_status", "already_in_terminal_state"):
                    job.preservadas = (job.preservadas or 0) + 1
                else:
                    job.falhas = (job.falhas or 0) + 1
                    if len(erros) < 50:
                        erros.append({"task_id": tid, "reason": reason})
                job.erros = list(erros)
                db.commit()

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
