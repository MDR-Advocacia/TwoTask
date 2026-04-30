"""
Dispatcher da fila de classificação AJUS — Chunk 2c.

Responsabilidades:
  - Distribuir itens pendentes da fila entre as contas online,
    em round-robin (least-recently-used).
  - Para cada conta escolhida, chamar o `AjusClassifRunner` pra
    processar N itens em sequência (uma sessão de browser
    autenticada cobre todo o batch — não loga 1x por item).
  - Atualizar status da conta (executando → online ou erro) e dos
    itens (pendente → processando → sucesso/erro).

Como é chamado:
  - **Manual:** endpoint `POST /ajus/classificacao/dispatch` —
    operador clica "Disparar pendentes" na UI.
  - **Periódico:** worker `scripts/ajus_runner_worker.py` no
    container `ajus-runner`, em loop com sleep configurável.

Concorrência:
  - 1 worker por conta (lock por `account_id` no banco via
    `set_status(EXECUTANDO)`). N contas = N workers paralelos.
  - Não dá pra rodar 2 instâncias do dispatcher pra mesma conta —
    `claim_for_run` usa `with_for_update(skip_locked=True)`, então
    a 2ª chamada pula a conta já claimed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ajus import (
    AJUS_ACCOUNT_ONLINE,
    AJUS_CLASSIF_PENDENTE,
    AjusClassificacaoQueue,
    AjusSessionAccount,
)
from app.services.ajus.classificacao_service import AjusClassificacaoService
from app.services.ajus.session_service import AjusSessionService

logger = logging.getLogger(__name__)


# Tamanho default do batch por conta. Configurável via param.
DEFAULT_BATCH_PER_ACCOUNT = 5


@dataclass
class DispatchResult:
    candidates: int
    success_count: int
    error_count: int
    success_ids: list[int]
    errored: list[dict]
    accounts_used: list[int]
    # Sinaliza que o login da conta caiu — dispatch_all usa pra marcar
    # conta como erro no release (em vez de devolver online e cair em
    # loop infinito de claim/falha).
    auth_failed: bool = False
    auth_error: str = ""


def _claim_pending_items(
    db: Session, account: AjusSessionAccount, *, limit: int,
) -> list[AjusClassificacaoQueue]:
    """
    Atomically pega até `limit` itens pendentes pra essa conta.
    Marca `dispatched_by_account_id` mas mantém status=pendente
    (o runner muda pra `processando` antes de cada item).
    """
    items = (
        db.query(AjusClassificacaoQueue)
        .filter(AjusClassificacaoQueue.status == AJUS_CLASSIF_PENDENTE)
        .filter(AjusClassificacaoQueue.dispatched_by_account_id.is_(None))
        .order_by(AjusClassificacaoQueue.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    for item in items:
        item.dispatched_by_account_id = account.id
    db.commit()
    return items


def _release_unprocessed(
    db: Session, account_id: int,
) -> None:
    """
    Limpa `dispatched_by_account_id` de itens que ficaram em
    pendente — caso o runner tenha morrido no meio do batch sem
    processar todos. Próxima chamada pode re-pegá-los.
    """
    (
        db.query(AjusClassificacaoQueue)
        .filter(
            AjusClassificacaoQueue.dispatched_by_account_id == account_id,
            AjusClassificacaoQueue.status == AJUS_CLASSIF_PENDENTE,
        )
        .update({AjusClassificacaoQueue.dispatched_by_account_id: None})
    )
    db.commit()


class AjusClassifDispatcher:
    """
    Orquestra a distribuição de itens pendentes entre contas online.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.session_service = AjusSessionService(db)
        self.classif_service = AjusClassificacaoService(db)

    # ── Dispatch global (todas as contas disponíveis) ───────────────

    def dispatch_all(
        self, *, batch_per_account: int = DEFAULT_BATCH_PER_ACCOUNT,
    ) -> DispatchResult:
        """
        Pega TODAS as contas online ativas, claim cada uma e roda
        um batch por conta. Retorna agregado.

        Não roda paralelo aqui (1 dispatcher = sequencial). Pra rodar
        N contas em paralelo de verdade, a paralelização está no nível
        do worker — cada conta tem seu próprio container/process. Esse
        método é mais útil pro endpoint manual.

        Respeita o flag global de pausa: se `is_paused=True`, retorna
        sem claimar nada (itens ja em curso por outro dispatcher
        terminam normalmente — pause eh "soft").
        """
        result = DispatchResult(
            candidates=0,
            success_count=0,
            error_count=0,
            success_ids=[],
            errored=[],
            accounts_used=[],
        )

        # Pausa global — se ativada, nao pega nenhum item.
        if self.classif_service.is_paused():
            logger.info(
                "AJUS dispatcher: pausa global ativa — nao claimando.",
            )
            return result

        # Claim N contas — para de tentar quando não há mais online.
        max_iterations = 20  # defensivo
        for _ in range(max_iterations):
            # Re-checa pausa a cada iteracao (operador pode pausar
            # entre batches numa execucao longa)
            if self.classif_service.is_paused():
                logger.info(
                    "AJUS dispatcher: pausa global ativada mid-loop — "
                    "interrompendo apos batch atual.",
                )
                break
            account = self.session_service.claim_for_run()
            if account is None:
                break
            acc_result: Optional[DispatchResult] = None
            try:
                acc_result = self._run_for_account(
                    account, batch_size=batch_per_account,
                )
                result.candidates += acc_result.candidates
                result.success_count += acc_result.success_count
                result.error_count += acc_result.error_count
                result.success_ids.extend(acc_result.success_ids)
                result.errored.extend(acc_result.errored)
                result.accounts_used.append(account.id)
            finally:
                # Se o login da conta caiu, marca como erro pra parar
                # o loop de reclaim. Senao, devolve pra online normal.
                if acc_result is not None and acc_result.auth_failed:
                    self.session_service.release_run(
                        account.id,
                        had_error=True,
                        error_message=acc_result.auth_error,
                    )
                else:
                    self.session_service.release_run(account.id)
                _release_unprocessed(self.db, account.id)
                # Se a conta caiu, NAO continua o loop tentando outras
                # iteracoes (proxima claim_for_run pode ate retornar None,
                # mas evita corrida com fast-poll do worker).
                if acc_result is not None and acc_result.auth_failed:
                    break

        return result

    # ── Dispatch pra uma conta específica (worker chama isso) ───────

    def run_for_account(
        self, account_id: int, *, batch_size: int = DEFAULT_BATCH_PER_ACCOUNT,
    ) -> DispatchResult:
        """
        Versão pública pra ser chamada pelo worker — assume que a conta
        já está online e disponível. Faz claim, processa, libera.

        Respeita o flag global de pausa.
        """
        # Pausa global — worker nao pega nada.
        if self.classif_service.is_paused():
            return DispatchResult(0, 0, 0, [], [], [])
        account = self.session_service.get_account(account_id)
        if account.status != AJUS_ACCOUNT_ONLINE:
            return DispatchResult(0, 0, 0, [], [], [])
        # Marca como executando
        self.session_service.set_status(account_id, "executando")
        try:
            r = self._run_for_account(account, batch_size=batch_size)
            r.accounts_used = [account_id]
            return r
        finally:
            self.session_service.release_run(account_id)
            _release_unprocessed(self.db, account_id)

    # ── Implementação interna ───────────────────────────────────────

    def _run_for_account(
        self, account: AjusSessionAccount, *, batch_size: int,
    ) -> DispatchResult:
        """
        Claim N itens, abre runner, processa, atualiza status.
        Encapsulado pra dispatch_all e run_for_account compartilharem.
        """
        result = DispatchResult(0, 0, 0, [], [], [])

        items = _claim_pending_items(self.db, account, limit=batch_size)
        if not items:
            logger.info(
                "AJUS dispatcher: account %d sem itens pendentes — pulando",
                account.id,
            )
            return result

        result.candidates = len(items)
        logger.info(
            "AJUS dispatcher: account %d processando %d item(ns)",
            account.id, len(items),
        )

        # Importa o runner aqui — o container API NÃO tem Playwright
        # instalado; o ajus-runner SIM. Esse import lazy permite que
        # esse módulo seja importável dos dois lados; só falha se o
        # caminho de `_run_for_account` for executado sem playwright.
        try:
            from app.services.ajus.classif_runner import AjusClassifRunner
        except ImportError as exc:
            logger.exception(
                "AJUS dispatcher: Playwright não disponível neste "
                "container. Esse caminho deve rodar só no ajus-runner.",
            )
            for item in items:
                self.classif_service.mark_error(
                    item.id,
                    error_message=f"Runner indisponível: {exc}",
                )
                result.errored.append({"id": item.id, "msg": str(exc)})
                result.error_count += 1
            return result

        with AjusClassifRunner(account, self.db) as runner:
            try:
                runner.ensure_logged_in()
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "AJUS dispatcher: falha no login da account %d — "
                    "devolvendo itens pra fila.", account.id,
                )
                # Devolve os itens pra fila (zera dispatched_by_account_id)
                # em vez de marcar como erro — o problema eh da CONTA,
                # nao do item. Operador faz Login de novo e tenta.
                for item in items:
                    item.dispatched_by_account_id = None
                    result.errored.append({"id": item.id, "msg": str(exc)})
                    result.error_count += 1
                self.db.commit()
                # Sinaliza pro dispatch_all marcar a conta como erro no
                # release (sem isso, conta volta pra online e o loop reclaima).
                result.auth_failed = True
                result.auth_error = str(exc)[:500]
                return result

            for item in items:
                try:
                    runner.classify_item(item)
                except Exception as exc:  # noqa: BLE001
                    # mark_error já foi chamado dentro de classify_item;
                    # aqui só registramos no resultado agregado.
                    logger.exception(
                        "AJUS dispatcher: erro inesperado em item %d",
                        item.id,
                    )
                    result.errored.append({"id": item.id, "msg": str(exc)})
                    result.error_count += 1
                    continue
                # Re-checa status pra contar correto
                self.db.refresh(item)
                if item.status == "sucesso":
                    result.success_count += 1
                    result.success_ids.append(item.id)
                else:
                    result.error_count += 1
                    result.errored.append({
                        "id": item.id,
                        "msg": item.error_message or "erro desconhecido",
                    })

        return result
