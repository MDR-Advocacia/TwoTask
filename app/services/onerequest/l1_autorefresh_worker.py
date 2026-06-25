"""Job horário do OneRequest: atualiza o STATUS L1 das DMIs que VENCEM HOJE.

Regra: de hora em hora, pra cada DMI ABERTA cujo prazo do BB == hoje, refaz a
checagem no Legal One (`verificar_status_l1`) — cacheando l1_* na linha, igual
ao botão "Atualizar status L1", só que automático. Assim o operador vê, sem
clicar, se a tarefa de quem vence hoje já foi respondida (Cumprida).

LIGADO por default. O operador controla com play/stop na UI (setting
`onerequest_l1_autorefresh_enabled`); ausência da setting = ligado. Roda em
thread do BackgroundScheduler, então abre a própria SessionLocal. Best-effort:
erro numa DMI não derruba as outras.
"""

import logging

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

JOB_ID = "onerequest_l1_autorefresh_hourly"
# Advisory lock: só um worker do uvicorn roda o auto-refresh por vez.
_LOCK_KEY = 826100002

SETTING_ENABLED = "onerequest_l1_autorefresh_enabled"
SETTING_LAST_RUN = "onerequest_l1_autorefresh_last_run"
SETTING_LAST_COUNT = "onerequest_l1_autorefresh_last_count"

_TRUE = ("1", "true", "yes", "on")


def is_enabled() -> bool:
    """Regra ligada? Default LIGADO (a setting só nasce no 1º toggle)."""
    from app.services.app_settings import get_setting

    return str(get_setting(SETTING_ENABLED, default="true")).strip().lower() in _TRUE


def _tick() -> None:
    from datetime import date, datetime, timezone

    from app.db.session import SessionLocal
    from app.models.onerequest import OnerequestSolicitacao, STATUS_SISTEMA_ABERTO
    from app.services.app_settings import set_setting
    from app.services.legal_one_client import LegalOneApiClient
    from app.services.onerequest._concurrency import single_worker_lock
    from app.services.onerequest.service import OnerequestService, _parse_prazo

    if not is_enabled():
        logger.info("OneRequest auto-refresh L1: regra DESLIGADA — tick ignorado.")
        return

    # Só um worker do uvicorn roda (evita 4× chamadas ao L1 + corrida nos l1_*).
    with single_worker_lock(_LOCK_KEY) as got:
        if not got:
            logger.info("OneRequest auto-refresh L1: outro worker já rodando — pulando.")
            return

        db = SessionLocal()
        try:
            service = OnerequestService(db)
            hoje = date.today()
            # Abertas; prazo é string DD/MM/YYYY, filtra "vence hoje" em Python.
            abertas = (
                db.query(OnerequestSolicitacao)
                .filter(OnerequestSolicitacao.status_sistema == STATUS_SISTEMA_ABERTO)
                .all()
            )
            alvos = [s for s in abertas if _parse_prazo(s.prazo) == hoje]
            logger.info("OneRequest auto-refresh L1: %s DMIs vencendo hoje.", len(alvos))

            ok = err = 0
            if alvos:
                client = LegalOneApiClient()
                for s in alvos:
                    try:
                        service.verificar_status_l1(s, client)
                        ok += 1
                    except Exception:
                        err += 1
                        logger.exception(
                            "OneRequest auto-refresh L1: falha na DMI %s.",
                            s.numero_solicitacao,
                        )
            logger.info(
                "OneRequest auto-refresh L1: concluído — %s ok, %s erro de %s.",
                ok, err, len(alvos),
            )
            set_setting(SETTING_LAST_RUN, datetime.now(timezone.utc).isoformat())
            set_setting(SETTING_LAST_COUNT, str(ok))
        except Exception:
            logger.exception("OneRequest auto-refresh L1: erro inesperado no tick.")
        finally:
            db.close()


def register_onerequest_l1_autorefresh_job(scheduler) -> None:
    """Registra o job horário no scheduler (a regra em si liga/desliga via setting)."""
    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(hours=1),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("OneRequest: job de auto-refresh L1 (de hora em hora) registrado.")
