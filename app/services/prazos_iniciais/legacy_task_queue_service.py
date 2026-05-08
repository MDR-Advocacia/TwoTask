from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.prazo_inicial import INTAKE_STATUS_SCHEDULED, PrazoInicialIntake
from app.models.prazo_inicial_legacy_task_queue import (
    QUEUE_STATUS_CANCELLED,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    PrazoInicialLegacyTaskCancellationItem,
)
from app.services.prazos_iniciais.legacy_task_helpers import (
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
)
from app.services.prazos_iniciais.legacy_task_circuit_breaker import (
    INFRASTRUCTURE_FAILURE_REASONS,
    get_circuit_breaker,
)

logger = logging.getLogger(__name__)

QUEUE_SUCCESS_REASONS = {
    "cancelled",
    "already_cancelled",
    "already_in_target_status",
}

# Motivos que tratamos como conclusão silenciosa (terminal sem ação): a
# task legada não existe no L1, então não há nada pra cancelar. Casos:
#   - USER_UPLOAD: operador subiu PDF manualmente, nunca houve task L1.
#   - Backlog antigo: operador finalizou task no L1 em status fora do
#     nosso filtro [0,3] (ex.: 1=Em andamento, 2=Concluído).
# Movemos pra COMPLETED em vez de FAILED pra parar de poluir o contador
# de falhas e o circuit breaker, mas preservamos `last_reason` pra
# auditoria. Antes (2026-05-06) entravam em FAILED e ficavam empacando
# o painel "Falhas por motivo: Task não encontrada".
QUEUE_NOOP_REASONS = {
    "task_not_found",
}

# Motivo gravado quando o operador cancela manualmente um item da fila pela UI.
MANUAL_CANCEL_REASON = "manually_cancelled"


def _resolve_cancellation_service() -> Any:
    """
    Factory do cancellation service. A pivotagem 2026-05-08 removeu a
    estrategia "playwright" (clickflow via subprocess Node) — agora e'
    sempre HTTP direto (POST em ModalEnvolvimentoEmLote, ~250ms/task).

    Import lazy pra evitar puxar `requests` + `filelock` em testes que
    mockam o cancellation_service via parametro do construtor.
    """
    from app.services.prazos_iniciais.legacy_task_http_cancellation_service import (
        LegacyTaskHttpCancellationService,
    )
    return LegacyTaskHttpCancellationService()


class PrazosIniciaisLegacyTaskQueueService:
    def __init__(
        self,
        db: Session,
        *,
        cancellation_service: Optional[Any] = None,
    ):
        self.db = db
        self.cancellation_service = (
            cancellation_service
            if cancellation_service is not None
            else _resolve_cancellation_service()
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _item_to_dict(self, item: PrazoInicialLegacyTaskCancellationItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "intake_id": item.intake_id,
            "lawsuit_id": item.lawsuit_id,
            "cnj_number": item.cnj_number,
            "office_id": item.office_id,
            "legacy_task_type_external_id": item.legacy_task_type_external_id,
            "legacy_task_subtype_external_id": item.legacy_task_subtype_external_id,
            "queue_status": item.queue_status,
            "attempt_count": item.attempt_count,
            "selected_task_id": item.selected_task_id,
            "cancelled_task_id": item.cancelled_task_id,
            "last_reason": item.last_reason,
            "last_attempt_at": item.last_attempt_at.isoformat() if item.last_attempt_at else None,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "last_error": item.last_error,
            "last_result": item.last_result,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }

    def sync_item_from_intake(
        self,
        intake: PrazoInicialIntake,
        *,
        commit: bool = True,
        legacy_task_type_external_id: int = DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        legacy_task_subtype_external_id: int = DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        force_queue: bool = False,  # legado, mantido por compat (agora redundante)
    ) -> Optional[PrazoInicialLegacyTaskCancellationItem]:
        """
        Garante que um intake tenha um item pendente na fila de
        cancelamento da task legada "Agendar Prazos".

        Politica nova (Pin0XX, 2026-05-07): enfileira assim que o intake
        tem identificador de processo (lawsuit_id ou cnj_number),
        independente do status. A intuicao: a chegada da publicacao ja
        torna a tarefa antiga obsoleta — nao importa se o operador vai
        agendar, devolver ou rejeitar. **Uma vez enfileirado, segue ate
        cancelar — nao reverte se o intake mudar de status posterior.**

        Excecao: fluxo de DEVOLUCAO (Pin019) cancela manualmente o item
        criado aqui no momento da transicao pra DEVOLUCAO_PENDENTE (em
        scheduling_service) — operador exclui no L1 manualmente.

        O parametro `force_queue` e' mantido por compat com call sites
        antigos mas e' redundante na nova politica (a regra `should_queue`
        nao depende mais do status do intake).
        """
        now = self._utcnow()
        item = intake.legacy_task_cancellation_item
        # Sem identificador de processo, nao tem o que cancelar no L1.
        should_queue = bool(intake.lawsuit_id) or bool(intake.cnj_number)

        if not should_queue:
            if commit:
                self.db.commit()
            return item

        if item is None:
            item = PrazoInicialLegacyTaskCancellationItem(
                intake_id=intake.id,
                lawsuit_id=intake.lawsuit_id,
                cnj_number=intake.cnj_number,
                office_id=intake.office_id,
                legacy_task_type_external_id=legacy_task_type_external_id,
                legacy_task_subtype_external_id=legacy_task_subtype_external_id,
                queue_status=QUEUE_STATUS_PENDING,
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
            self.db.add(item)
            intake.legacy_task_cancellation_item = item
        else:
            # Item ja existe. Atualiza dados (lawsuit_id pode ter sido
            # resolvido depois da criacao do item, p.ex.) mas NAO reverte
            # status terminal — operador pode ter cancelado manualmente
            # (CANCELLED) ou worker concluiu (COMPLETED). Esses dois nao
            # voltam pra PENDING; quem quiser reprocessar usa a UI
            # ("Reprocessar" reseta attempt_count via reprocess_item).
            config_changed = (
                item.legacy_task_type_external_id != legacy_task_type_external_id
                or item.legacy_task_subtype_external_id != legacy_task_subtype_external_id
            )
            item.lawsuit_id = intake.lawsuit_id
            item.cnj_number = intake.cnj_number
            item.office_id = intake.office_id
            item.legacy_task_type_external_id = legacy_task_type_external_id
            item.legacy_task_subtype_external_id = legacy_task_subtype_external_id
            if item.queue_status == QUEUE_STATUS_FAILED or config_changed:
                # Reset pra dar nova chance. Inclui FAILED (re-sync da
                # uma chance "automatica" em vez de exigir clique manual)
                # e config_changed (mudanca de tipo/subtipo invalida
                # tentativa anterior porque vai bater em outra task L1).
                item.queue_status = QUEUE_STATUS_PENDING
                item.attempt_count = 0
                item.completed_at = None
                item.last_error = None
                item.last_result = None
                item.last_reason = None
                item.selected_task_id = None
                item.cancelled_task_id = None
            item.updated_at = now

        if commit:
            self.db.commit()
        return item

    def get_item(self, item_id: int) -> Optional[PrazoInicialLegacyTaskCancellationItem]:
        return (
            self.db.query(PrazoInicialLegacyTaskCancellationItem)
            .options(joinedload(PrazoInicialLegacyTaskCancellationItem.intake))
            .filter(PrazoInicialLegacyTaskCancellationItem.id == item_id)
            .first()
        )

    def _build_list_query(
        self,
        *,
        queue_status: Optional[str] = None,
        intake_id: Optional[int] = None,
        cnj_number: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ):
        """Query base reusada por list_items + count_items pra garantir
        que total e pagina visivel batem (mesmo conjunto de filtros)."""
        query = self.db.query(PrazoInicialLegacyTaskCancellationItem)
        if queue_status:
            query = query.filter(PrazoInicialLegacyTaskCancellationItem.queue_status == queue_status)
        if intake_id is not None:
            query = query.filter(PrazoInicialLegacyTaskCancellationItem.intake_id == intake_id)
        if cnj_number:
            cleaned = cnj_number.strip()
            if cleaned:
                query = query.filter(
                    PrazoInicialLegacyTaskCancellationItem.cnj_number.ilike(f"%{cleaned}%")
                )
        if since is not None:
            query = query.filter(
                PrazoInicialLegacyTaskCancellationItem.updated_at >= since
            )
        if until is not None:
            query = query.filter(
                PrazoInicialLegacyTaskCancellationItem.updated_at <= until
            )
        return query

    def list_items(
        self,
        *,
        queue_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        intake_id: Optional[int] = None,
        cnj_number: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        query = self._build_list_query(
            queue_status=queue_status,
            intake_id=intake_id,
            cnj_number=cnj_number,
            since=since,
            until=until,
        ).order_by(PrazoInicialLegacyTaskCancellationItem.id.desc())
        return [
            self._item_to_dict(item)
            for item in query.limit(limit).offset(offset).all()
        ]

    def count_items(
        self,
        *,
        queue_status: Optional[str] = None,
        intake_id: Optional[int] = None,
        cnj_number: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> int:
        """Total absoluto de items que batem com os filtros (independente
        de limit/offset). Usado pelo paginador da UI mostrar 'Pagina X
        de Y' corretamente."""
        return self._build_list_query(
            queue_status=queue_status,
            intake_id=intake_id,
            cnj_number=cnj_number,
            since=since,
            until=until,
        ).count()

    # Status IDs terminais no L1: task ja nao precisa ser tocada.
    # 1=Cumprido, 2=Nao cumprido, 3=Cancelado.
    _L1_TERMINAL_STATUS_IDS = {1, 2, 3}

    def _pre_check_terminal_status(
        self,
        item: PrazoInicialLegacyTaskCancellationItem,
    ) -> Optional[dict[str, Any]]:
        """
        Consulta a API L1 pra ver se item.selected_task_id ja esta em
        estado terminal antes de invocar o RPA. Retorna dict com `reason`
        e `current_status_id` se for o caso (caller deve pular RPA e
        marcar COMPLETED). Retorna None se nao deu pra concluir e o
        fluxo deve seguir pro RPA.
        """
        if not item.selected_task_id:
            return None
        # Lazy import — evita acoplar o init do modulo a validacao do
        # LegalOneApiClient (env vars).
        try:
            from app.services.legal_one_client import LegalOneApiClient
            import requests as _requests
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "legacy_task_queue.pre_check.import_failed item_id=%s err=%s",
                item.id, exc,
            )
            return None
        try:
            client = LegalOneApiClient()
        except Exception as exc:  # noqa: BLE001
            # Sem credenciais ou config — nao bloqueia o fluxo, deixa
            # cair no RPA (que tem suas proprias creds).
            logger.warning(
                "legacy_task_queue.pre_check.client_init_failed item_id=%s err=%s",
                item.id, exc,
            )
            return None
        try:
            task = client.get_task_by_id(int(item.selected_task_id))
        except _requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                # Task nao existe mais no L1 — terminal sem acao.
                return {
                    "success": True,
                    "reason": "task_not_found",
                    "task_id": item.selected_task_id,
                    "current_status_id": None,
                    "skipped_rpa": True,
                    "pre_check_via": "api_l1_get_task",
                }
            logger.warning(
                "legacy_task_queue.pre_check.http_error item_id=%s status=%s",
                item.id, status,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "legacy_task_queue.pre_check.api_error item_id=%s err=%s",
                item.id, exc,
            )
            return None
        try:
            current_status_id = int(task.get("statusId"))
        except (TypeError, ValueError):
            return None
        if current_status_id not in self._L1_TERMINAL_STATUS_IDS:
            return None
        reason = (
            "already_cancelled"
            if current_status_id == 3
            else "already_in_terminal_state"
        )
        return {
            "success": True,
            "reason": reason,
            "task_id": item.selected_task_id,
            "current_status_id": current_status_id,
            "skipped_rpa": True,
            "pre_check_via": "api_l1_get_task",
        }

    def process_item(
        self,
        item: PrazoInicialLegacyTaskCancellationItem,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = self._utcnow()
        tick_start = time.monotonic()
        item_id = item.id
        intake_id = item.intake_id
        cnj_number = item.cnj_number
        lawsuit_id = item.lawsuit_id

        item.queue_status = QUEUE_STATUS_PROCESSING
        item.attempt_count = int(item.attempt_count or 0) + 1
        item.last_attempt_at = now
        item.updated_at = now
        if commit:
            self.db.commit()
            self.db.refresh(item)
        else:
            self.db.flush()

        logger.info(
            "legacy_task_queue.process_item.start",
            extra={
                "event": "legacy_task_queue.process_item.start",
                "item_id": item_id,
                "intake_id": intake_id,
                "cnj_number": cnj_number,
                "lawsuit_id": lawsuit_id,
                "attempt_count": item.attempt_count,
            },
        )

        # Pre-check API L1: se a task ja esta em estado terminal (cumprida,
        # nao cumprida, cancelada), nao vale a pena invocar o RPA — ele
        # falharia em UI weirdness ("nao posso cancelar tarefa cumprida")
        # ou cancelaria outra task pendente do mesmo processo por engano.
        # Esse skip economiza 5-10s de subprocess Node + login Playwright
        # por item ja resolvido, e nao polui o painel de "Falhas".
        skip_via_pre_check = self._pre_check_terminal_status(item)
        if skip_via_pre_check is not None:
            duration_ms = int((time.monotonic() - tick_start) * 1000)
            logger.info(
                "legacy_task_queue.process_item.skip_terminal_via_api",
                extra={
                    "event": "legacy_task_queue.process_item.skip_terminal_via_api",
                    "item_id": item_id,
                    "intake_id": intake_id,
                    "cnj_number": cnj_number,
                    "lawsuit_id": lawsuit_id,
                    "selected_task_id": item.selected_task_id,
                    "current_status_id": skip_via_pre_check.get("current_status_id"),
                    "reason": skip_via_pre_check.get("reason"),
                    "duration_ms": duration_ms,
                },
            )
            item.queue_status = QUEUE_STATUS_COMPLETED
            item.last_reason = skip_via_pre_check.get("reason")
            item.last_result = skip_via_pre_check
            current_sid = skip_via_pre_check.get("current_status_id")
            if current_sid == 3:
                # Ja cancelada externamente — marca cancelled_task_id pro mesmo task.
                item.cancelled_task_id = item.selected_task_id
            item.completed_at = self._utcnow()
            item.last_error = None
            item.updated_at = self._utcnow()
            if commit:
                self.db.commit()
                self.db.refresh(item)
            return {
                "item": self._item_to_dict(item),
                "result": skip_via_pre_check,
            }

        try:
            result = self.cancellation_service.cancel_task(
                cnj_number=item.cnj_number,
                lawsuit_id=item.lawsuit_id,
                task_type_external_id=item.legacy_task_type_external_id,
                task_subtype_external_id=item.legacy_task_subtype_external_id,
                candidate_status_ids=[0, 3],
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - tick_start) * 1000)
            logger.exception(
                "legacy_task_queue.process_item.exception",
                extra={
                    "event": "legacy_task_queue.process_item.exception",
                    "item_id": item_id,
                    "intake_id": intake_id,
                    "cnj_number": cnj_number,
                    "lawsuit_id": lawsuit_id,
                    "attempt_count": item.attempt_count,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
            )
            item.queue_status = QUEUE_STATUS_FAILED
            item.last_reason = "exception"
            item.last_error = str(exc)
            item.updated_at = self._utcnow()
            if commit:
                self.db.commit()
                self.db.refresh(item)
            return {
                "item": self._item_to_dict(item),
                "result": None,
            }

        item.last_result = result
        item.last_reason = result.get("reason")
        item.selected_task_id = result.get("task_id")
        reason_now = result.get("reason")
        if reason_now in QUEUE_SUCCESS_REASONS:
            item.queue_status = QUEUE_STATUS_COMPLETED
            item.cancelled_task_id = result.get("task_id")
            item.completed_at = self._utcnow()
            item.last_error = None
        elif reason_now in QUEUE_NOOP_REASONS:
            # Não há task L1 pra cancelar — terminal sem ação. Mantém o
            # last_reason ("task_not_found") pra auditoria mas marca
            # COMPLETED pra parar de tentar e tirar do balde de falhas.
            item.queue_status = QUEUE_STATUS_COMPLETED
            item.completed_at = self._utcnow()
            item.last_error = None
        else:
            item.queue_status = QUEUE_STATUS_FAILED
            item.last_error = (
                result.get("runner_error")
                or reason_now
                or "Falha ao cancelar task legada."
            )
        item.updated_at = self._utcnow()

        duration_ms = int((time.monotonic() - tick_start) * 1000)
        logger.info(
            "legacy_task_queue.process_item.finish",
            extra={
                "event": "legacy_task_queue.process_item.finish",
                "item_id": item_id,
                "intake_id": intake_id,
                "cnj_number": cnj_number,
                "lawsuit_id": lawsuit_id,
                "attempt_count": item.attempt_count,
                "duration_ms": duration_ms,
                "queue_status": item.queue_status,
                "reason": item.last_reason,
                "task_id": result.get("task_id"),
            },
        )

        if commit:
            self.db.commit()
            self.db.refresh(item)
        return {
            "item": self._item_to_dict(item),
            "result": result,
        }

    # ── Recovery de items zumbis (PROCESSANDO sem update) ────────────────
    # Cenario: worker pegou item, marcou PROCESSANDO, e nunca atualizou —
    # subprocess Node travou, container reiniciou, exception silenciosa, etc.
    # Sem recovery, esses items ficam visiveis pro usuario como "Processando"
    # pra sempre — inflam o painel e nao sao mais elegiveis pro proximo tick
    # (que so pega PENDENTE/FALHA).

    def _zombie_threshold_minutes(self) -> int:
        return max(
            1,
            int(settings.prazos_iniciais_legacy_task_zombie_threshold_minutes or 5),
        )

    def _zombie_query(self, threshold_minutes: Optional[int] = None):
        threshold = threshold_minutes or self._zombie_threshold_minutes()
        cutoff = self._utcnow() - timedelta(minutes=threshold)
        return self.db.query(PrazoInicialLegacyTaskCancellationItem).filter(
            PrazoInicialLegacyTaskCancellationItem.queue_status == QUEUE_STATUS_PROCESSING,
            # last_attempt_at e' o timestamp em que entrou em PROCESSANDO.
            # Se for None (raro, mas defensivo), usamos updated_at.
            (
                PrazoInicialLegacyTaskCancellationItem.last_attempt_at < cutoff
            ) | (
                (PrazoInicialLegacyTaskCancellationItem.last_attempt_at.is_(None))
                & (PrazoInicialLegacyTaskCancellationItem.updated_at < cutoff)
            ),
        )

    def count_zombies(self, threshold_minutes: Optional[int] = None) -> int:
        return int(self._zombie_query(threshold_minutes).count() or 0)

    def list_zombies(
        self,
        *,
        threshold_minutes: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        items = (
            self._zombie_query(threshold_minutes)
            .order_by(PrazoInicialLegacyTaskCancellationItem.last_attempt_at.asc().nullsfirst())
            .limit(max(1, int(limit)))
            .all()
        )
        return [self._item_to_dict(it) for it in items]

    def quarantine_exhausted_items(
        self,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Move pra FALHA todos os items em PENDENTE/FALHA com attempt_count
        >= max_attempts. Roda no inicio de cada tick do worker periodico
        (process_pending_items).

        Antes desse sweep (2026-05-08), items que estouravam o cap de
        retries ficavam num limbo: o worker filtrava attempt_count <
        max_attempts e nunca os via, mas eles continuavam em PENDENTE
        invisiveis no painel de saude (totals_by_status mostrava o
        agregado bruto). Resultado: 35 items presos sem nunca virarem
        FALHA, eligible_count=0 sem motivo aparente.

        Apos o sweep, eles aparecem no card "Falhas" do operador, que
        decide entre Reprocessar (zera attempt_count) ou Cancelar.

        Retorna {"quarantined_count": N, "max_attempts": M, "items": [...]}
        """
        from app.core.config import settings as _settings
        max_attempts = max(
            1,
            int(_settings.prazos_iniciais_legacy_task_max_attempts or 5),
        )
        candidates = (
            self.db.query(PrazoInicialLegacyTaskCancellationItem)
            .filter(
                PrazoInicialLegacyTaskCancellationItem.queue_status.in_(
                    [QUEUE_STATUS_PENDING, QUEUE_STATUS_FAILED]
                ),
                PrazoInicialLegacyTaskCancellationItem.attempt_count
                >= max_attempts,
            )
            .all()
        )
        # Filtra os que ja' estao em FALHA com last_reason correto pra
        # evitar UPDATE no-op em todo tick (idempotencia + log limpo).
        quarantined: list[dict[str, Any]] = []
        for item in candidates:
            already_quarantined = (
                item.queue_status == QUEUE_STATUS_FAILED
                and item.last_reason == "max_attempts_reached"
            )
            if already_quarantined:
                continue
            item.queue_status = QUEUE_STATUS_FAILED
            item.last_reason = "max_attempts_reached"
            item.last_error = (
                f"max_attempts_reached (attempt_count={item.attempt_count} "
                f">= max={max_attempts}). Reprocessar zera o contador e "
                "tenta de novo; Pular cancela definitivamente."
            )
            item.updated_at = self._utcnow()
            quarantined.append(self._item_to_dict(item))
            logger.warning(
                "legacy_task_queue.quarantine_exhausted",
                extra={
                    "event": "legacy_task_queue.quarantine_exhausted",
                    "item_id": item.id,
                    "intake_id": item.intake_id,
                    "attempt_count": item.attempt_count,
                    "max_attempts": max_attempts,
                    "previous_status": (
                        QUEUE_STATUS_PENDING
                        if item.queue_status == QUEUE_STATUS_FAILED
                        else item.queue_status
                    ),
                },
            )
        if commit and quarantined:
            self.db.commit()
        return {
            "quarantined_count": len(quarantined),
            "max_attempts": max_attempts,
            "items": quarantined,
        }

    def recover_zombies(
        self,
        *,
        threshold_minutes: Optional[int] = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Devolve pra PENDENTE todos os items que estao em PROCESSANDO ha mais
        de `threshold_minutes` minutos sem update. Incrementa attempt_count
        e grava `last_error="zombie_recovered (...)"` pra rastreabilidade.

        Roda no inicio de cada tick do worker periodico (process_pending_items)
        e pode ser triggered manualmente via endpoint /recover-zombies.

        Retorna {"recovered_count": N, "threshold_minutes": M, "items": [...]}
        """
        threshold = threshold_minutes or self._zombie_threshold_minutes()
        zombies = self._zombie_query(threshold).all()
        recovered: list[dict[str, Any]] = []
        for item in zombies:
            stuck_seconds = None
            ref_at = item.last_attempt_at or item.updated_at
            if ref_at is not None:
                stuck_seconds = int((self._utcnow() - ref_at).total_seconds())
            item.queue_status = QUEUE_STATUS_PENDING
            item.last_error = (
                f"zombie_recovered (PROCESSANDO ha {stuck_seconds}s sem update — "
                f"threshold={threshold}min). Worker tentara de novo no proximo tick."
            ) if stuck_seconds is not None else (
                f"zombie_recovered (PROCESSANDO sem update — threshold={threshold}min)."
            )
            item.last_reason = "zombie_recovered"
            item.updated_at = self._utcnow()
            recovered.append(self._item_to_dict(item))
            logger.warning(
                "legacy_task_queue.zombie_recovered",
                extra={
                    "event": "legacy_task_queue.zombie_recovered",
                    "item_id": item.id,
                    "intake_id": item.intake_id,
                    "selected_task_id": item.selected_task_id,
                    "stuck_seconds": stuck_seconds,
                    "threshold_minutes": threshold,
                    "attempt_count": item.attempt_count,
                },
            )
        if commit and recovered:
            self.db.commit()
        return {
            "recovered_count": len(recovered),
            "threshold_minutes": threshold,
            "items": recovered,
        }

    def process_pending_items(
        self,
        *,
        limit: int = 20,
        intake_id: Optional[int] = None,
    ) -> dict[str, Any]:
        tick_id = uuid.uuid4().hex[:12]
        tick_start = time.monotonic()
        cb = get_circuit_breaker()
        # Intakes pedidos explicitamente (pós-confirmação de agendamento) ignoram
        # o circuit breaker — é chamada sob demanda, não o worker periódico.
        if intake_id is None and cb.is_tripped():
            snapshot = cb.snapshot()
            logger.warning(
                "legacy_task_queue.tick.skipped_circuit_breaker",
                extra={
                    "event": "legacy_task_queue.tick.skipped_circuit_breaker",
                    "tick_id": tick_id,
                    "tripped_until": (
                        snapshot.tripped_until.isoformat()
                        if snapshot.tripped_until
                        else None
                    ),
                    "last_trip_reason": snapshot.last_trip_reason,
                    "consecutive_failures": snapshot.consecutive_failures,
                },
            )
            return {
                "processed_count": 0,
                "eligible_count": 0,
                "items": [],
                "circuit_breaker_tripped": True,
                "circuit_breaker_tripped_during_tick": False,
                "success_count": 0,
                "failure_count": 0,
                "duration_ms": 0,
                "tick_id": tick_id,
            }

        # Recovery de zumbis ANTES de buscar elegiveis: items em PROCESSANDO
        # ha muito tempo voltam pra PENDENTE e ficam disponiveis pro proprio
        # tick em curso. Soh roda no worker periodico (intake_id is None) —
        # chamadas pontuais pos-confirmacao nao mexem em items de outros intakes.
        zombie_recovered_count = 0
        if intake_id is None:
            try:
                zombie_summary = self.recover_zombies(commit=True)
                zombie_recovered_count = int(zombie_summary.get("recovered_count", 0))
                if zombie_recovered_count > 0:
                    logger.info(
                        "legacy_task_queue.tick.zombies_recovered",
                        extra={
                            "event": "legacy_task_queue.tick.zombies_recovered",
                            "tick_id": tick_id,
                            "recovered_count": zombie_recovered_count,
                            "threshold_minutes": zombie_summary.get("threshold_minutes"),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "legacy_task_queue.tick.zombie_recovery_failed tick_id=%s err=%s",
                    tick_id, exc,
                )

        # Quarentena: items em PENDENTE/FALHA que estouraram max_attempts
        # viram FALHA com last_reason="max_attempts_reached". Antes desse
        # sweep, eles ficavam em PENDENTE invisiveis (filtro de elegibilidade
        # exclui attempt_count >= max), e eligible_count caia pra 0 sem
        # motivo aparente. Soh roda no tick periodico — chamadas pontuais
        # com intake_id ignoram cap e nao precisam dessa limpeza.
        if intake_id is None:
            try:
                quarantine_summary = self.quarantine_exhausted_items(commit=True)
                quarantined_count = int(quarantine_summary.get("quarantined_count", 0))
                if quarantined_count > 0:
                    logger.info(
                        "legacy_task_queue.tick.exhausted_quarantined",
                        extra={
                            "event": "legacy_task_queue.tick.exhausted_quarantined",
                            "tick_id": tick_id,
                            "quarantined_count": quarantined_count,
                            "max_attempts": quarantine_summary.get("max_attempts"),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "legacy_task_queue.tick.quarantine_failed tick_id=%s err=%s",
                    tick_id, exc,
                )

        query = (
            self.db.query(PrazoInicialLegacyTaskCancellationItem)
            .order_by(PrazoInicialLegacyTaskCancellationItem.id.asc())
        )
        if intake_id is not None:
            query = query.filter(PrazoInicialLegacyTaskCancellationItem.intake_id == intake_id)
        else:
            # Worker periódico: pega PENDING e FAILED, mas pula items que
            # já estouraram max_attempts (evita loop eterno em layout_drift
            # / runner_error permanente). Operador pode reprocessar manual
            # pela UI ("Reprocessar" reseta attempt_count). Chamada com
            # intake_id (background task pós-confirmação) ignora o cap —
            # é uma execução pontual, faz sentido tentar mesmo no limite.
            max_attempts = max(1, int(settings.prazos_iniciais_legacy_task_max_attempts or 5))
            query = query.filter(
                PrazoInicialLegacyTaskCancellationItem.queue_status.in_(
                    [QUEUE_STATUS_PENDING, QUEUE_STATUS_FAILED]
                ),
                PrazoInicialLegacyTaskCancellationItem.attempt_count < max_attempts,
            )

        items = query.limit(limit).all()
        eligible_count = len(items)

        logger.info(
            "legacy_task_queue.tick.start",
            extra={
                "event": "legacy_task_queue.tick.start",
                "tick_id": tick_id,
                "eligible_count": eligible_count,
                "intake_id": intake_id,
                "limit": limit,
            },
        )

        # Guarda porque depois usamos o valor no summary devolvido — o loop
        # pode pular itens que mudaram de status entre o SELECT e o refresh,
        # então processed_count != eligible_count é o caso geral.
        snapshot_eligible_count = eligible_count

        rate_limit_seconds = max(
            0.0,
            float(settings.prazos_iniciais_legacy_task_cancel_rate_limit_seconds or 0.0),
        )

        processed: list[dict[str, Any]] = []
        success_count = 0
        failure_count = 0
        circuit_breaker_tripped_during_tick = False
        for index, item in enumerate(items):
            self.db.refresh(item)
            if item.queue_status not in {QUEUE_STATUS_PENDING, QUEUE_STATUS_FAILED}:
                continue
            if index > 0 and rate_limit_seconds > 0.0:
                time.sleep(rate_limit_seconds)

            outcome = self.process_item(item, commit=True)
            processed.append(outcome)

            reason = outcome["item"].get("last_reason")

            # NOOP (task_not_found) conta como sucesso pro CB e pro
            # contador — o item virou COMPLETED no process_item, então
            # tratar como falha aqui daria contagem inconsistente.
            if reason in QUEUE_SUCCESS_REASONS or reason in QUEUE_NOOP_REASONS:
                success_count += 1
                cb.record_success()
            else:
                failure_count += 1
                # Apenas falhas de infraestrutura (auth/timeout/exception)
                # alimentam o breaker. Falhas de dado (task_not_found, etc.)
                # não contam — são incrementadas em failure_count mas saem do
                # branch aqui sem tocar no breaker.
                if intake_id is None and reason in INFRASTRUCTURE_FAILURE_REASONS:
                    tripped_now = cb.record_failure(reason)
                    if tripped_now:
                        circuit_breaker_tripped_during_tick = True
                        snapshot = cb.snapshot()
                        logger.warning(
                            "legacy_task_queue.tick.circuit_breaker_tripped",
                            extra={
                                "event": "legacy_task_queue.tick.circuit_breaker_tripped",
                                "tick_id": tick_id,
                                "item_id": item.id,
                                "intake_id": item.intake_id,
                                "tripped_until": (
                                    snapshot.tripped_until.isoformat()
                                    if snapshot.tripped_until
                                    else None
                                ),
                                "consecutive_failures": snapshot.consecutive_failures,
                                "threshold": snapshot.threshold,
                                "reason": reason,
                            },
                        )
                        break  # deixa o próximo tick decidir

        duration_ms = int((time.monotonic() - tick_start) * 1000)
        logger.info(
            "legacy_task_queue.tick.finish",
            extra={
                "event": "legacy_task_queue.tick.finish",
                "tick_id": tick_id,
                "eligible_count": eligible_count,
                "processed_count": len(processed),
                "success_count": success_count,
                "failure_count": failure_count,
                "duration_ms": duration_ms,
                "circuit_breaker_tripped_during_tick": circuit_breaker_tripped_during_tick,
                "intake_id": intake_id,
            },
        )

        return {
            "processed_count": len(processed),
            "eligible_count": snapshot_eligible_count,
            "items": processed,
            "circuit_breaker_tripped": False,
            "circuit_breaker_tripped_during_tick": circuit_breaker_tripped_during_tick,
            "success_count": success_count,
            "failure_count": failure_count,
            "duration_ms": duration_ms,
            "tick_id": tick_id,
            "zombies_recovered_count": zombie_recovered_count,
        }

    # ── ações do operador (UI) ─────────────────────────────────────────

    def reprocess_item(self, item_id: int) -> Optional[dict[str, Any]]:
        """
        Reset manual: zera status pra PENDENTE e limpa erro pro próximo tick
        agarrar. Não executa o runner aqui — mantém idempotência e mantém a
        execução no worker/endpoint de processamento.

        Zera tambem attempt_count: depois de 2026-05-06 o worker periodico
        skipa items com attempt_count >= max_attempts pra nao loopar; o
        reprocess manual eh justamente o caminho do operador pra dizer
        "tenta de novo do zero" depois de uma intervencao no L1 (ex.:
        login OnePass renovado).
        """
        item = self.get_item(item_id)
        if item is None:
            return None
        now = self._utcnow()
        item.queue_status = QUEUE_STATUS_PENDING
        item.attempt_count = 0
        item.last_error = None
        item.last_reason = None
        item.last_result = None
        item.completed_at = None
        item.updated_at = now
        self.db.commit()
        self.db.refresh(item)
        logger.info(
            "legacy_task_queue.reprocess_item",
            extra={
                "event": "legacy_task_queue.reprocess_item",
                "item_id": item.id,
                "intake_id": item.intake_id,
                "attempt_count": item.attempt_count,
            },
        )
        return self._item_to_dict(item)

    def cancel_item(self, item_id: int) -> Optional[dict[str, Any]]:
        """Cancela manualmente um item (o operador decide abortar o retry)."""
        item = self.get_item(item_id)
        if item is None:
            return None
        now = self._utcnow()
        item.queue_status = QUEUE_STATUS_CANCELLED
        item.last_reason = MANUAL_CANCEL_REASON
        item.updated_at = now
        self.db.commit()
        self.db.refresh(item)
        logger.info(
            "legacy_task_queue.cancel_item",
            extra={
                "event": "legacy_task_queue.cancel_item",
                "item_id": item.id,
                "intake_id": item.intake_id,
            },
        )
        return self._item_to_dict(item)

    def cancel_item_for_intake(
        self,
        intake: PrazoInicialIntake,
        *,
        reason: str = "intake_devolucao",
        commit: bool = True,
    ) -> Optional[PrazoInicialLegacyTaskCancellationItem]:
        """
        Cancela o item da fila vinculado a este intake (se existir e
        nao estiver em estado terminal).

        Usado pelo fluxo de DEVOLUCAO (Pin019): a politica nova
        enfileira na criacao do intake, mas devolucao requer exclusao
        manual no L1 — entao no momento que o intake vira
        DEVOLUCAO_PENDENTE, o item correspondente da queue sai do
        balde de cancelamento automatico.

        Idempotente: se ja esta em CANCELLED ou COMPLETED, no-op.
        """
        item = intake.legacy_task_cancellation_item
        if item is None:
            return None
        if item.queue_status in {QUEUE_STATUS_CANCELLED, QUEUE_STATUS_COMPLETED}:
            return item
        item.queue_status = QUEUE_STATUS_CANCELLED
        item.last_reason = reason
        item.updated_at = self._utcnow()
        if commit:
            self.db.commit()
        logger.info(
            "legacy_task_queue.cancel_item_for_intake",
            extra={
                "event": "legacy_task_queue.cancel_item_for_intake",
                "item_id": item.id,
                "intake_id": item.intake_id,
                "reason": reason,
            },
        )
        return item

    # ── métricas para /metrics e exports ───────────────────────────────

    def aggregate_metrics(self, *, hours: int = 24) -> dict[str, Any]:
        """
        Snapshot agregado da fila pro endpoint de observabilidade.

        Inclui:
        - Total por status (PENDENTE/PROCESSANDO/CONCLUIDO/FALHA/CANCELADO).
        - Contagem e latência média (completed_at - last_attempt_at) dos
          concluídos na janela `hours`.
        - Contagem de falhas agrupadas por `last_reason` na janela `hours`.
        - Snapshot do circuit breaker (pra UI mostrar o badge sem precisar
          bater em outro endpoint).
        """
        hours = max(1, int(hours))
        now = self._utcnow()
        window_start = now - timedelta(hours=hours)

        status_rows = (
            self.db.query(
                PrazoInicialLegacyTaskCancellationItem.queue_status,
                func.count(PrazoInicialLegacyTaskCancellationItem.id),
            )
            .group_by(PrazoInicialLegacyTaskCancellationItem.queue_status)
            .all()
        )
        totals_by_status: dict[str, int] = {
            status: int(count or 0) for status, count in status_rows
        }

        # Latência dos concluídos na janela (computada em Python pra não
        # depender de função específica de SQL — SQLite nos testes não tem
        # EXTRACT(EPOCH) etc).
        completed_rows = (
            self.db.query(
                PrazoInicialLegacyTaskCancellationItem.last_attempt_at,
                PrazoInicialLegacyTaskCancellationItem.completed_at,
            )
            .filter(
                PrazoInicialLegacyTaskCancellationItem.queue_status == QUEUE_STATUS_COMPLETED,
                PrazoInicialLegacyTaskCancellationItem.completed_at >= window_start,
            )
            .all()
        )
        latencies_ms: list[int] = []
        for attempt_at, completed_at in completed_rows:
            if attempt_at is None or completed_at is None:
                continue
            delta = completed_at - attempt_at
            ms = int(delta.total_seconds() * 1000)
            if ms < 0:
                continue
            latencies_ms.append(ms)
        completed_in_window = len(completed_rows)
        avg_latency_ms = (
            int(sum(latencies_ms) / len(latencies_ms)) if latencies_ms else None
        )

        failure_reason_rows = (
            self.db.query(
                PrazoInicialLegacyTaskCancellationItem.last_reason,
                func.count(PrazoInicialLegacyTaskCancellationItem.id),
            )
            .filter(
                PrazoInicialLegacyTaskCancellationItem.queue_status == QUEUE_STATUS_FAILED,
                PrazoInicialLegacyTaskCancellationItem.last_attempt_at >= window_start,
            )
            .group_by(PrazoInicialLegacyTaskCancellationItem.last_reason)
            .all()
        )
        failures_by_reason: dict[str, int] = {
            (reason or "unknown"): int(count or 0) for reason, count in failure_reason_rows
        }
        failures_in_window = sum(failures_by_reason.values())

        cb_snapshot = get_circuit_breaker().snapshot()
        circuit_breaker = {
            "tripped": cb_snapshot.tripped,
            "tripped_until": (
                cb_snapshot.tripped_until.isoformat()
                if cb_snapshot.tripped_until
                else None
            ),
            "consecutive_failures": cb_snapshot.consecutive_failures,
            "threshold": cb_snapshot.threshold,
            "cooldown_minutes": cb_snapshot.cooldown_minutes,
            "last_trip_reason": cb_snapshot.last_trip_reason,
            "last_trip_at": (
                cb_snapshot.last_trip_at.isoformat()
                if cb_snapshot.last_trip_at
                else None
            ),
            "last_reset_at": (
                cb_snapshot.last_reset_at.isoformat()
                if cb_snapshot.last_reset_at
                else None
            ),
            "counted_reasons": list(cb_snapshot.counted_reasons),
        }

        # Zombie info: items em PROCESSANDO ha mais de N min sem update.
        # Usado pelo painel pra mostrar "X zumbis detectados" e botao
        # "recuperar manualmente" quando >0.
        zombie_threshold = self._zombie_threshold_minutes()
        zombie_count_now = self.count_zombies(zombie_threshold)

        return {
            "window_hours": hours,
            "window_start": window_start.isoformat(),
            "now": now.isoformat(),
            "totals_by_status": totals_by_status,
            "completed_in_window": completed_in_window,
            "failures_in_window": failures_in_window,
            "failures_by_reason_in_window": failures_by_reason,
            "avg_latency_ms_in_window": avg_latency_ms,
            "latency_samples_in_window": len(latencies_ms),
            "circuit_breaker": circuit_breaker,
            "rate_limit_seconds": float(
                settings.prazos_iniciais_legacy_task_cancel_rate_limit_seconds or 0.0
            ),
            "zombie_count": zombie_count_now,
            "zombie_threshold_minutes": zombie_threshold,
        }
