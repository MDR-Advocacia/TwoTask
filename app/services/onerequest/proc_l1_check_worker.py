"""Job do OneRequest: verificação PROATIVA de existência do processo no L1.

De tempos em tempos, pra cada DMI ABERTA ainda NÃO checada (proc_l1_checado_em
IS NULL), resolve o processo no Legal One (CNJ -> NPJ) SEM criar tarefa e grava
se a pasta existe (proc_l1_*). Assim, pouco depois de uma DMI chegar, o painel já
sinaliza se o processo está no L1 — sem o operador precisar clicar (ex.: o caso
"viabilidade de ajuizamento" cujo número nunca virou pasta aqui).

Processa em LOTES por tick pra não martelar a API do L1. LIGADO por default
(setting `onerequest_proc_l1_check_enabled`). Advisory lock: só um worker do
uvicorn roda. Best-effort: erro numa DMI não derruba as outras.
"""

import logging

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

JOB_ID = "onerequest_proc_l1_check_hourly"
# Advisory lock dedicado (sync=...001, auto-refresh=...002, este=...003).
_LOCK_KEY = 826100003

SETTING_ENABLED = "onerequest_proc_l1_check_enabled"
# Quantas DMIs não-checadas resolver por tick (limita carga no L1).
_BATCH = 40

_TRUE = ("1", "true", "yes", "on")


def is_enabled() -> bool:
    """Regra ligada? Default LIGADO (a setting só nasce no 1º toggle)."""
    from app.services.app_settings import get_setting

    return str(get_setting(SETTING_ENABLED, default="true")).strip().lower() in _TRUE


def _tick() -> None:
    from app.db.session import SessionLocal
    from app.models.onerequest import OnerequestSolicitacao, STATUS_SISTEMA_ABERTO
    from app.services.legal_one_client import LegalOneApiClient
    from app.services.onerequest._concurrency import single_worker_lock
    from app.services.onerequest.service import OnerequestService

    if not is_enabled():
        logger.info("OneRequest verif. processo L1: regra DESLIGADA — tick ignorado.")
        return

    # Só um worker do uvicorn roda (evita 4× chamadas ao L1).
    with single_worker_lock(_LOCK_KEY) as got:
        if not got:
            logger.info("OneRequest verif. processo L1: outro worker já rodando — pulando.")
            return

        db = SessionLocal()
        try:
            service = OnerequestService(db)
            # Abertas ainda NÃO checadas — lote por tick (mais recentes primeiro).
            alvos = (
                db.query(OnerequestSolicitacao)
                .filter(
                    OnerequestSolicitacao.status_sistema == STATUS_SISTEMA_ABERTO,
                    OnerequestSolicitacao.proc_l1_checado_em.is_(None),
                )
                .order_by(OnerequestSolicitacao.id.desc())
                .limit(_BATCH)
                .all()
            )
            if not alvos:
                logger.info("OneRequest verif. processo L1: nada pendente de checagem.")
                return

            logger.info("OneRequest verif. processo L1: checando %s DMIs.", len(alvos))
            ok = achados = err = 0
            client = LegalOneApiClient()
            for s in alvos:
                try:
                    res = service.verificar_processo_l1(s, client)
                    ok += 1
                    if res.get("encontrado"):
                        achados += 1
                except Exception:
                    err += 1
                    logger.exception(
                        "OneRequest verif. processo L1: falha na DMI %s.",
                        s.numero_solicitacao,
                    )
            logger.info(
                "OneRequest verif. processo L1: concluído — %s checadas (%s no L1), %s erro.",
                ok, achados, err,
            )
        except Exception:
            logger.exception("OneRequest verif. processo L1: erro inesperado no tick.")
        finally:
            db.close()


def register_onerequest_proc_l1_check_job(scheduler) -> None:
    """Registra o job (de hora em hora) + 1ª rodada logo após o boot."""
    from datetime import datetime, timedelta

    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(hours=1),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now() + timedelta(seconds=45),
    )
    logger.info("OneRequest: job de verificação de processo no L1 (horário) registrado.")
