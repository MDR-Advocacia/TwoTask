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

import concurrent.futures
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
    AJUS_ACCOUNT_EXECUTANDO,
    AJUS_ACCOUNT_LOGANDO,
    AJUS_ACCOUNT_ONLINE,
    AJUS_CLASSIF_PENDENTE,
    AJUS_CLASSIF_PROCESSANDO,
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


def _recover_stale_state(db) -> None:
    """
    Recovery one-shot no boot do worker.

    Se o container anterior morreu mid-batch (SIGKILL/OOM/redeploy
    abrupto), o `finally` que chama `release_run()` nao roda — entao
    contas ficam presas em status `executando` pra sempre, e o
    dispatcher (que so pega contas `online`) nao tem como pegar
    nada. Resultado: worker idle silencioso, fila parada, todos os
    cards mostrando "Executando" sem nada acontecer.

    Por definicao, no boot do worker nenhum batch esta rodando, entao
    qualquer estado em-andamento eh stale e seguro de limpar:
      - contas `executando` -> volta pra `online`
      - itens `processando` -> volta pra `pendente` + libera claim
      - itens `pendente` com claim -> libera claim (proximo dispatch
        re-distribui entre as contas)
    """
    stale_accounts = (
        db.query(AjusSessionAccount)
        .filter(AjusSessionAccount.status == AJUS_ACCOUNT_EXECUTANDO)
        .all()
    )
    for acc in stale_accounts:
        logger.warning(
            "Recovery: conta %d (%s) presa em 'executando' — "
            "runner anterior morreu mid-batch. Voltando pra 'online'.",
            acc.id, acc.label,
        )
        acc.status = AJUS_ACCOUNT_ONLINE

    proc_count = (
        db.query(AjusClassificacaoQueue)
        .filter(AjusClassificacaoQueue.status == AJUS_CLASSIF_PROCESSANDO)
        .update(
            {
                AjusClassificacaoQueue.status: AJUS_CLASSIF_PENDENTE,
                AjusClassificacaoQueue.dispatched_by_account_id: None,
            },
            synchronize_session=False,
        )
    )

    released_count = (
        db.query(AjusClassificacaoQueue)
        .filter(
            AjusClassificacaoQueue.status == AJUS_CLASSIF_PENDENTE,
            AjusClassificacaoQueue.dispatched_by_account_id.isnot(None),
        )
        .update(
            {AjusClassificacaoQueue.dispatched_by_account_id: None},
            synchronize_session=False,
        )
    )

    if stale_accounts or proc_count or released_count:
        db.commit()
        logger.warning(
            "Recovery concluido: %d conta(s) destravada(s), "
            "%d item(ns) 'processando' voltaram pra fila, "
            "%d item(ns) pendentes liberados de claim.",
            len(stale_accounts), proc_count, released_count,
        )
    else:
        logger.info("Recovery: nenhum estado stale encontrado.")


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


def _process_account_isolated(account_id: int, batch_per_account: int) -> dict:
    """
    Roda um batch pra UMA conta em uma thread isolada — cria session
    propria, dispatcher proprio, browser proprio (Playwright sync API
    requer recursos por thread, nao compartilha entre threads).
    Retorna dict com sucessos/erros pra agregacao no caller.
    """
    db = SessionLocal()
    try:
        result = AjusClassifDispatcher(db).run_for_account(
            account_id, batch_size=batch_per_account,
        )
        return {
            "account_id": account_id,
            "candidates": result.candidates,
            "success_count": result.success_count,
            "error_count": result.error_count,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Falha no thread da account %d: %s", account_id, exc,
        )
        return {
            "account_id": account_id,
            "candidates": 0, "success_count": 0,
            "error_count": 0, "exception": str(exc),
        }
    finally:
        db.close()


def _dispatch_pending_classifications(db) -> None:
    """
    Se ha itens pendentes, dispara processamento PARALELO entre as
    contas online ativas. Cada conta vira uma thread independente
    (session + dispatcher + browser proprios). Mirror tinha esse
    comportamento via ThreadPoolExecutor — sem ele, contas processam
    sequencialmente (1 por vez) e desperdica capacidade.

    Cap maximo de threads = min(qtd contas online, 8) — defensivo
    contra bugs que possam acumular workers se contas crescerem muito.
    """
    if not _has_pending_items_for_anyone(db):
        return

    from app.services.ajus.classificacao_service import AjusClassificacaoService
    if AjusClassificacaoService(db).is_paused():
        logger.info("AJUS dispatcher: pausa global ativa — nao claimando.")
        return

    online_accounts = (
        db.query(AjusSessionAccount.id)
        .filter(AjusSessionAccount.is_active.is_(True))
        .filter(AjusSessionAccount.status == AJUS_ACCOUNT_ONLINE)
        .all()
    )
    account_ids = [a.id for a in online_accounts]
    if not account_ids:
        return

    max_parallel = max(1, min(len(account_ids), 8))
    batch_per_account = settings.ajus_runner_batch_per_account

    if len(account_ids) == 1:
        out = _process_account_isolated(account_ids[0], batch_per_account)
        if out.get("candidates", 0) > 0:
            logger.info(
                "Dispatch: %d candidato(s), %d sucesso(s), %d erro(s), "
                "contas usadas: [%d]",
                out["candidates"], out["success_count"],
                out["error_count"], out["account_id"],
            )
        return

    logger.info(
        "AJUS dispatcher: paralelizando entre %d conta(s) "
        "(max threads=%d, batch=%d).",
        len(account_ids), max_parallel, batch_per_account,
    )
    total_candidates = 0
    total_success = 0
    total_errors = 0
    accounts_used: list[int] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_parallel,
            thread_name_prefix="ajus-runner",
        ) as executor:
            futures = {
                executor.submit(
                    _process_account_isolated, acc_id, batch_per_account,
                ): acc_id
                for acc_id in account_ids
            }
            for future in concurrent.futures.as_completed(futures):
                acc_id = futures[future]
                try:
                    res = future.result()
                except Exception as exc:
                    logger.exception(
                        "Thread da account %d levantou: %s", acc_id, exc,
                    )
                    continue
                cand = res.get("candidates", 0)
                if cand > 0:
                    accounts_used.append(res["account_id"])
                total_candidates += cand
                total_success += res.get("success_count", 0)
                total_errors += res.get("error_count", 0)
    except Exception:
        logger.exception("Falha nao tratada no dispatch paralelo")
        return

    if total_candidates > 0:
        logger.info(
            "Dispatch (paralelo): %d candidato(s), %d sucesso(s), "
            "%d erro(s), contas usadas: %s",
            total_candidates, total_success, total_errors, accounts_used,
        )


# ─── Main loop ───────────────────────────────────────────────────────


def main() -> int:
    interval = int(getattr(
        settings, "ajus_runner_poll_interval_seconds", 30,
    ) or 30)
    logger.info(
        "AJUS runner worker iniciado. Poll interval: %ds. Aguardando trabalho…",
        interval,
    )

    # Recovery one-shot: limpa estado stale de runner anterior que
    # morreu mid-batch (sem rodar release_run/finally). Sem isso,
    # contas ficam presas em 'executando' e o dispatcher nao acha
    # nada pra processar — worker idle silencioso pra sempre.
    try:
        with SessionLocal() as recovery_db:
            _recover_stale_state(recovery_db)
    except Exception:  # noqa: BLE001
        logger.exception("Recovery no boot falhou — segue mesmo assim.")

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

        # Sleep entre ciclos: tick rapido de 2s pra detectar trabalho
        # novo (operador clicou "Disparar" no UI; fila ganhou item via
        # intake). Sai do sleep cedo se houver, pra processar em ~2s.
        # O `interval` configurado vira o intervalo MAXIMO de espera
        # (sem trabalho novo). Checa shutdown a cada tick.
        elapsed = 0
        while elapsed < interval:
            if _shutdown:
                break
            time.sleep(2)
            elapsed += 2
            try:
                with SessionLocal() as fast_db:
                    if _has_pending_items_for_anyone(fast_db):
                        break
            except Exception:
                # Falha na fast-check nao quebra o ciclo; sleep continua.
                pass

    logger.info("AJUS runner worker encerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
