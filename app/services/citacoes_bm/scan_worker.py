"""Job diário do módulo Citações BM (APScheduler).

Todo dia de madrugada:
1. Puxa do L1 os processos novos do Banco Master/Réu (creationDate >= hoje).
2. Varre TODOS os processos ativos no DataJud, trazendo as movimentações
   novas (marcadas como não-lidas; candidatos a citação destacados).

Roda em thread do BackgroundScheduler, então abre a própria SessionLocal.
Idempotente: o fingerprint evita reinserir movimento já capturado, e o
dedupe por CNJ evita recriar processo já monitorado.
"""

import logging

from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

JOB_ID = "citacoes_bm_daily_scan"

# Hora local do servidor (Coolify roda em America/Sao_Paulo).
SCAN_HOUR = 4
SCAN_MINUTE = 0


def _tick() -> None:
    from app.db.session import SessionLocal
    from app.services.citacoes_bm.service import CitacoesBMService

    db = SessionLocal()
    try:
        service = CitacoesBMService(db=db)

        # 1) Ingestão automática dos processos novos do dia (best-effort).
        try:
            ing = service.ingest_l1_auto()
            logger.info(
                "Citações BM: ingestão L1 automática — %s criados (%s no L1).",
                ing.get("criados"), ing.get("encontrados_l1"),
            )
        except Exception:
            logger.exception("Citações BM: falha na ingestão L1 automática.")

        # 2) Varredura DataJud de todos os ativos.
        res = service.scan_all()
        logger.info(
            "Citações BM: varredura diária — %s processos | ok=%s sem_hits=%s "
            "erro=%s | %s movimentos novos.",
            res.get("processos"), res.get("ok"), res.get("sem_hits"),
            res.get("erro"), res.get("novos_movimentos"),
        )
    except Exception:
        logger.exception("Citações BM: erro inesperado no tick diário.")
    finally:
        db.close()


def register_citacoes_bm_scan_job(scheduler) -> None:
    """Registra o job diário no scheduler."""
    scheduler.add_job(
        _tick,
        trigger=CronTrigger(hour=SCAN_HOUR, minute=SCAN_MINUTE),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Citações BM: job diário registrado (cron %02d:%02d).",
        SCAN_HOUR, SCAN_MINUTE,
    )
