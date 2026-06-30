"""Cancelamento em lote de tarefas duplicadas do board (fase B).

Reusa o método maduro `LegacyTaskHttpCancellationService.cancel_task` (método B:
POST web + verify API; cobre tarefas de Workflow; pré-check de terminal — NUNCA
cancela Cumprida; idempotente). Cada cancelamento reverifica o status ao vivo no
L1, então rodar de novo é seguro (no-op nas já canceladas).

O lote roda numa THREAD daemon e grava o progresso na tabela `perf_cancel_job`,
pra o polling enxergar o status mesmo com vários workers do uvicorn. ~0,3 task/s.
"""

import logging
import threading
import uuid

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.performance import PerfCancelJob

logger = logging.getLogger(__name__)

_MAX = 5000  # trava de segurança por lote


def iniciar(team: str, subtipo: str, task_ids: list) -> str:
    """Cria o job, dispara a thread e devolve o job_id pro polling."""
    ids = [int(t) for t in task_ids if t][:_MAX]
    job_id = uuid.uuid4().hex[:12]
    db = SessionLocal()
    try:
        db.add(
            PerfCancelJob(
                id=job_id, team=team, subtipo=subtipo, status="running", total=len(ids), erros=[]
            )
        )
        db.commit()
    finally:
        db.close()
    threading.Thread(target=_run, args=(job_id, ids), daemon=True).start()
    return job_id


def _run(job_id: str, ids: list) -> None:
    from app.services.prazos_iniciais.legacy_task_http_cancellation_service import (
        LegacyTaskHttpCancellationService,
    )

    svc = LegacyTaskHttpCancellationService()
    db = SessionLocal()
    try:
        job = db.get(PerfCancelJob, job_id)
        erros: list = []
        for tid in ids:
            reason = None
            ok = False
            try:
                r = svc.cancel_task(task_id=tid)
                reason = r.get("reason")
                ok = bool(r.get("success"))
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
        job.terminado_em = func.now()
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("job de cancelamento %s estourou", job_id)
        try:
            j = db.get(PerfCancelJob, job_id)
            if j:
                j.status = "done"
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
            "total": j.total or 0,
            "feito": j.feito or 0,
            "cancelled": j.cancelled or 0,
            "preservadas": j.preservadas or 0,
            "falhas": j.falhas or 0,
            "erros": j.erros or [],
        }
    finally:
        db.close()
