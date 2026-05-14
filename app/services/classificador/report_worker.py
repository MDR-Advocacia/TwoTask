"""Worker periodico do Classificador — geracao de relatorios em background.

Tick a cada 10s, varre relatorios em PROCESSANDO e roda
`_generate_report_background` (build_report_data + generate_xlsx/pdf +
save_report). Atualiza pra PRONTO ou FALHOU.

Motivacao: FastAPI `BackgroundTasks` se mostrou instavel em producao
(worker do gunicorn pode reciclar antes do task terminar, dependendo
da config; alem disso, falhas no task NAO loggam). APScheduler ja' esta
configurado e roda confiavelmente (vide poll_worker.py).

Registrado no startup do main.py via `register_classificador_report_job`.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.session import SessionLocal
from app.models.classificador import (
    ClassificadorRelatorio,
    REL_STATUS_PROCESSANDO,
)

logger = logging.getLogger(__name__)


REPORT_TICK_INTERVAL_SECONDS = 10
# Tempo MIN apos o requested_at antes de o worker pegar — evita race
# com BackgroundTasks que pode estar processando (se BG estiver ok)
PICKUP_DELAY_SECONDS = 5
# Lock pra evitar 2 workers competindo pelo mesmo relatorio na mesma
# instancia (multi-worker em Coolify/gunicorn nao tem garantia
# distribuida — mas o status_check_and_set abaixo serializa via DB)
_running_now: set[int] = set()
_running_lock = threading.Lock()


def _claim_relatorio(db, rel_id: int) -> bool:
    """Tenta marcar o relatorio como 'sendo processado por mim' usando
    optimistic locking: atualiza started_at SE ainda esta em PROCESSANDO
    e o memory-lock local nao registra.

    Retorna True se conseguiu o claim.
    """
    with _running_lock:
        if rel_id in _running_now:
            return False
        _running_now.add(rel_id)
    return True


def _release_relatorio(rel_id: int) -> None:
    with _running_lock:
        _running_now.discard(rel_id)


def _run_pending_report(rel_id: int) -> None:
    """Worker que gera 1 relatorio (busca info pelo ID, monta, salva)."""
    from datetime import datetime as _dt
    from app.models.classificador import (
        REL_FORMAT_XLSX,
        REL_STATUS_FALHOU,
        REL_STATUS_PRONTO,
    )
    from app.services.classificador.report_data import build_report_data
    from app.services.classificador.report_pdf import generate_pdf_report
    from app.services.classificador.report_storage import save_report
    from app.services.classificador.report_xlsx import generate_xlsx_report

    db = SessionLocal()
    try:
        rel = (
            db.query(ClassificadorRelatorio)
            .filter(ClassificadorRelatorio.id == rel_id)
            .first()
        )
        if rel is None:
            logger.warning("report_worker: relatorio #%s sumiu", rel_id)
            return
        if rel.status != REL_STATUS_PROCESSANDO:
            logger.info(
                "report_worker: relatorio #%s ja' nao esta PROCESSANDO (status=%s)",
                rel_id, rel.status,
            )
            return

        logger.info(
            "report_worker: gerando relatorio #%s (lote=%s formato=%s)",
            rel.id, rel.lote_id, rel.formato,
        )
        try:
            data = build_report_data(db, rel.lote_id)
            if rel.formato == REL_FORMAT_XLSX:
                file_bytes = generate_xlsx_report(data)
                ext = "xlsx"
            else:
                file_bytes = generate_pdf_report(data)
                ext = "pdf"
            stored = save_report(file_bytes, extension=ext)
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
            logger.info(
                "report_worker: relatorio #%s PRONTO (bytes=%d)",
                rel.id, rel.file_bytes or 0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "report_worker: falha relatorio #%s lote=%s formato=%s",
                rel.id, rel.lote_id, rel.formato,
            )
            rel.status = REL_STATUS_FALHOU
            rel.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            rel.finished_at = _dt.utcnow()
            db.commit()
    finally:
        db.close()


def _tick() -> None:
    """Roda 1 iteracao — varre relatorios em PROCESSANDO e processa."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=PICKUP_DELAY_SECONDS)
        pendentes = (
            db.query(ClassificadorRelatorio)
            .filter(ClassificadorRelatorio.status == REL_STATUS_PROCESSANDO)
            .filter(ClassificadorRelatorio.requested_at <= cutoff)
            .order_by(ClassificadorRelatorio.requested_at.asc())
            .limit(5)  # max 5 por tick — evita esgotar pool DB
            .all()
        )
        if not pendentes:
            return
        logger.info(
            "report_worker: %d relatorio(s) pendente(s)",
            len(pendentes),
        )
    finally:
        db.close()

    # Processa cada um (NOVA sessao por relatorio — _run_pending_report
    # abre/fecha db) com lock local pra evitar reprocessar
    for rel in pendentes:
        if not _claim_relatorio(None, rel.id):
            continue
        try:
            _run_pending_report(rel.id)
        finally:
            _release_relatorio(rel.id)


def register_classificador_report_job(scheduler: BackgroundScheduler) -> None:
    """Registra o tick periodico no scheduler global."""
    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(seconds=REPORT_TICK_INTERVAL_SECONDS),
        id="classificador_report_worker",
        name="Classificador — geracao de relatorios em background",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # primeira rodada imediata
        max_instances=1,  # nao deixa 2 ticks rodarem em paralelo
        coalesce=True,
    )
    logger.info(
        "classificador_report_worker: registrado (interval=%ds)",
        REPORT_TICK_INTERVAL_SECONDS,
    )
