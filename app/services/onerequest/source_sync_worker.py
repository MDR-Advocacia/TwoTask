"""Job horário do OneRequest: LÊ o Postgres da FONTE (onde a RPA local escreve)
e espelha pro `onr_solicitacoes` do Flow.

Arquitetura nova: o app da RPA foi desmembrado — a RPA roda no escritório e
grava num Postgres separado (recurso Coolify do OneRequest); o Flow CONSOME de
lá. Este job lê de hora em hora e faz upsert (Flow é dono do tratamento; só os
campos capturados + status_sistema são espelhados).

READ-ONLY DE VERDADE: a sessão de leitura é aberta com `readonly=True`, então o
Postgres rejeita qualquer escrita acidental na fonte. Ligado só quando
`ONEREQUEST_SOURCE_DB_URL` está setada (env do Coolify). Roda em thread do
BackgroundScheduler, então abre a própria SessionLocal pro lado do Flow.
"""

import logging

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

JOB_ID = "onerequest_source_sync_hourly"

# Só os campos CAPTURADOS pela RPA (o tratamento vive no Flow e é preservado).
_SOURCE_QUERY = (
    "SELECT numero_solicitacao, titulo, npj_direcionador, prazo, texto_dmi, "
    "numero_processo, polo, recebido_em, status_sistema FROM solicitacoes"
)


def _tick() -> None:
    import psycopg2
    import psycopg2.extras

    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.services.onerequest.intake_service import OnerequestIntakeService

    dsn = settings.onerequest_source_db_url
    if not dsn:
        logger.info("OneRequest sync: ONEREQUEST_SOURCE_DB_URL não setada — pulando tick.")
        return

    # 1) LÊ a fonte — sessão READ-ONLY (o Postgres barra qualquer escrita).
    try:
        conn = psycopg2.connect(dsn, connect_timeout=15)
        try:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(_SOURCE_QUERY)
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        logger.exception("OneRequest sync: falha ao LER o Postgres da fonte.")
        return

    logger.info("OneRequest sync: %s linhas lidas da fonte.", len(rows))

    # 2) Espelha pro onr_solicitacoes (preserva tratamento do Flow).
    db = SessionLocal()
    try:
        res = OnerequestIntakeService(db).sync_from_source(rows)
        logger.info("OneRequest sync concluído: %s", res)
    except Exception:
        logger.exception("OneRequest sync: falha ao espelhar pro onr_solicitacoes.")
    finally:
        db.close()


def register_onerequest_source_sync_job(scheduler) -> None:
    """Registra o job de sync (de hora em hora) + uma 1ª execução no boot."""
    from datetime import datetime, timedelta

    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(hours=1),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        # 1ª rodada logo após o boot (popula o que a RPA já gravou), depois horária.
        next_run_time=datetime.now() + timedelta(seconds=30),
    )
    logger.info("OneRequest: job de sync da fonte (horário) registrado.")
