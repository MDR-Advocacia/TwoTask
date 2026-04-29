"""
Entry-point do container ajus-runner — Chunk 2c.

Loop principal:
  1. Conecta no DB (mesma URL que a API).
  2. A cada `AJUS_RUNNER_POLL_INTERVAL_SECONDS`:
     a) Pra cada conta com status `logando` → faz login via runner
        (resolve IP-code se aparecer).
     b) Pra cada conta com status `online`, ativa, com itens
        pendentes na fila → roda batch via dispatcher.
  3. Continua até sinal SIGTERM (Coolify restart) ou SIGINT.

NÃO depende de FastAPI nem APScheduler — script standalone.
Logs vão pra stdout, container do Coolify captura.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from typing import Optional

from sqlalchemy.orm import sessionmaker

# Adiciona raiz do projeto ao sys.path pra resolver `app.*`
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.ajus import (  # noqa: E402
    AJUS_ACCOUNT_LOGANDO,
    AJUS_ACCOUNT_ONLINE,
    AJUS_CLASSIF_PENDENTE,
    AjusClassificacaoQueue,
    AjusSessionAccount,
)
from app.services.ajus.classif_dispatcher import AjusClassifDispatcher  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ajus_runner_worker")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ─── Sinal handling ──────────────────────────────────────────────────


_shutdown = False


def _on_signal(signum, frame):
    global _shutdown
    logger.info("Sinal %s recebido — encerrando após o ciclo atual.", signum)
    _shutdown = True


signal.signal(signal.SIGTERM, _on_signal)
signal.signal(signal.SIGINT, _on_signal)


# ─── Helpers ─────────────────────────────────────────────────────────


def _has_pending_items_for_anyone(db) -> bool:
    """Existe pelo menos 1 item pendente sem conta atribuída?"""
    return (
        db.query(AjusClassificacaoQueue.id)
        .filter(AjusClassificacaoQueue.status == AJUS_CLASSIF_PENDENTE)
        .filter(AjusClassificacaoQueue.dispatched_by_account_id.is_(None))
        .first()
    ) is not None


def _login_pending_accounts(db) -> None:
    """
    Pra toda conta em `logando`, dispara o runner pra fazer login.
    Se AJUS pedir IP-code, runner marca a conta como `aguardando_ip_code`
    e aguarda o operador submeter via UI (polling no DB).
    """
    accounts = (
        db.query(AjusSessionAccount)
        .filter(AjusSessionAccount.is_active.is_(True))
        .filter(AjusSessionAccount.status == AJUS_ACCOUNT_LOGANDO)
        .all()
    )
    if not accounts:
        return

    from app.services.ajus.classif_runner import AjusClassifRunner

    for account in accounts:
        logger.info(
            "Iniciando login da account %d (%s)…",
            account.id, account.label,
        )
        try:
            with AjusClassifRunner(account, db) as runner:
                runner.ensure_logged_in()
            logger.info("Login OK pra account %d", account.id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Falha no login da account %d — runner deixa em status erro/offline.",
                account.id,
            )


def _dispatch_pending_classifications(db) -> None:
    """
    Se há itens pendentes, roda o dispatcher (que distribui em
    round-robin entre contas online).
    """
    if not _has_pending_items_for_anyone(db):
        return
    try:
        result = AjusClassifDispatcher(db).dispatch_all(
            batch_per_account=settings.ajus_runner_batch_per_account,
        )
        if result.candidates > 0:
            logger.info(
                "Dispatch: %d candidato(s), %d sucesso(s), %d erro(s), "
                "contas usadas: %s",
                result.candidates,
                result.success_count,
                result.error_count,
                result.accounts_used,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Falha não tratada no dispatch_all")


# ─── Main loop ───────────────────────────────────────────────────────


def main() -> int:
    interval = int(getattr(
        settings, "ajus_runner_poll_interval_seconds", 30,
    ) or 30)
    logger.info(
        "AJUS runner worker iniciado. Poll interval: %ds. Aguardando trabalho…",
        interval,
    )

    while not _shutdown:
        db = SessionLocal()
        try:
            _login_pending_accounts(db)
            if _shutdown:
                break
            _dispatch_pending_classifications(db)
        except Exception:  # noqa: BLE001
            logger.exception("Erro no ciclo do worker — segue.")
        finally:
            db.close()

        # Sleep com checagem rápida de shutdown
        for _ in range(interval):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("AJUS runner worker encerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
