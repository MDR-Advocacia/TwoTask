"""Job diário: ingestão do Minha Equipe via download do relatório do L1.

O relatório "Agenda Analytics" é gerado pelo L1 de manhã (~9h, demora porque é
grande). O job roda das **9h às 12h30 BRT, a cada 30 min**: o primeiro tick que
encontrar o relatório DE HOJE ingere; os seguintes pulam (já sincronizou). É o
retry-até-aparecer que o operador pediu. Advisory lock = só um worker do uvicorn.
"""

import logging

from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

JOB_ID = "perf_minha_equipe_ingest_daily"
# Advisory lock dedicado (onerequest usa ...001/002/003).
_LOCK_KEY = 826100004


def _tick() -> None:
    from app.db.session import SessionLocal
    from app.services.onerequest._concurrency import single_worker_lock
    from app.services.performance.report_ingest import baixar_e_ingerir, ja_sincronizou_hoje

    if ja_sincronizou_hoje():
        logger.info("Minha Equipe ingest: já sincronizou hoje — tick ignorado.")
        return

    with single_worker_lock(_LOCK_KEY) as got:
        if not got:
            logger.info("Minha Equipe ingest: outro worker já rodando — pulando.")
            return
        if ja_sincronizou_hoje():  # double-check sob o lock
            return

        db = SessionLocal()
        try:
            res = baixar_e_ingerir(db)
            if res.get("ok"):
                logger.info(
                    "Minha Equipe ingest: OK — %s tarefas do relatório de %s.",
                    res.get("tarefas"), res.get("data"),
                )
            else:
                logger.info("Minha Equipe ingest: ainda não ingeriu — %s.", res.get("motivo"))
        except Exception:
            logger.exception("Minha Equipe ingest: erro inesperado no tick.")
        finally:
            db.close()


def register_perf_ingest_job(scheduler) -> None:
    scheduler.add_job(
        _tick,
        trigger=CronTrigger(hour="9-12", minute="0,30", timezone="America/Sao_Paulo"),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Minha Equipe: job de ingestão diária (9h-12h30 BRT, 30/30min) registrado.")
