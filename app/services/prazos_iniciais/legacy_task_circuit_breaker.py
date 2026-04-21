"""
Circuit breaker da fila de cancelamento da task legada "Agendar Prazos".

Estado in-memory (por processo). Quando o worker encontra uma sequência de
falhas de infraestrutura (auth/timeout/exception Python), ele "trip" o
circuit breaker por `cooldown_minutes`, durante os quais o tick é pulado
inteiro pra dar tempo do L1 normalizar (ou pra alguém olhar o caso).

Categorias de falha que CONTAM pro contador (`INFRASTRUCTURE_FAILURE_REASONS`):
  - auth_failure   — login OnePass falhou ou foi redirecionado
  - timeout        — Playwright/HTTP timed out
  - exception      — exception não tratada no service Python

Categorias que NÃO contam (são problemas de dado, não de infra):
  - task_not_found, lawsuit_not_found, layout_drift, verification_failed,
    runner_error genérico

Sucesso (`record_success`) zera o contador independentemente do reason.

Estado é global de processo. Em deploys multi-worker (gunicorn workers>1),
cada processo tem seu próprio breaker — aceitável porque o APScheduler já
roda 1 instância de job por processo, e as decisões de skip são localmente
consistentes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings


INFRASTRUCTURE_FAILURE_REASONS: frozenset[str] = frozenset({
    "auth_failure",
    "timeout",
    "exception",
})


@dataclass
class CircuitBreakerSnapshot:
    """Snapshot serializável pro endpoint /metrics."""

    tripped: bool
    tripped_until: Optional[datetime]
    consecutive_failures: int
    threshold: int
    cooldown_minutes: int
    last_trip_reason: Optional[str]
    last_trip_at: Optional[datetime]
    last_reset_at: Optional[datetime]
    counted_reasons: list[str] = field(default_factory=lambda: sorted(INFRASTRUCTURE_FAILURE_REASONS))


class _CircuitBreakerState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._tripped_until: Optional[datetime] = None
        self._last_trip_reason: Optional[str] = None
        self._last_trip_at: Optional[datetime] = None
        self._last_reset_at: Optional[datetime] = None

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _is_tripped_locked(self) -> bool:
        if self._tripped_until is None:
            return False
        if self._now() >= self._tripped_until:
            # cooldown venceu — limpa pra próxima leitura ser limpa
            self._tripped_until = None
            return False
        return True

    # ── leitura ────────────────────────────────────────────────────────
    def is_tripped(self) -> bool:
        with self._lock:
            return self._is_tripped_locked()

    def snapshot(self) -> CircuitBreakerSnapshot:
        with self._lock:
            return CircuitBreakerSnapshot(
                tripped=self._is_tripped_locked(),
                tripped_until=self._tripped_until,
                consecutive_failures=self._consecutive_failures,
                threshold=max(1, int(settings.prazos_iniciais_legacy_task_circuit_breaker_threshold)),
                cooldown_minutes=max(
                    1,
                    int(settings.prazos_iniciais_legacy_task_circuit_breaker_cooldown_minutes),
                ),
                last_trip_reason=self._last_trip_reason,
                last_trip_at=self._last_trip_at,
                last_reset_at=self._last_reset_at,
            )

    # ── escrita ────────────────────────────────────────────────────────
    def record_success(self) -> None:
        with self._lock:
            if self._consecutive_failures > 0 or self._tripped_until is not None:
                self._last_reset_at = self._now()
            self._consecutive_failures = 0
            self._tripped_until = None

    def record_failure(self, reason: Optional[str]) -> bool:
        """
        Registra uma falha. Retorna True se o circuit breaker tripou nesta
        chamada (útil pra log estruturado do service).
        """
        if not reason or reason not in INFRASTRUCTURE_FAILURE_REASONS:
            return False
        with self._lock:
            self._consecutive_failures += 1
            threshold = max(1, int(settings.prazos_iniciais_legacy_task_circuit_breaker_threshold))
            if self._consecutive_failures >= threshold and self._tripped_until is None:
                cooldown = max(
                    1,
                    int(settings.prazos_iniciais_legacy_task_circuit_breaker_cooldown_minutes),
                )
                self._tripped_until = self._now() + timedelta(minutes=cooldown)
                self._last_trip_reason = reason
                self._last_trip_at = self._now()
                return True
        return False

    def reset(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._tripped_until = None
            self._last_trip_reason = None
            self._last_reset_at = self._now()


_circuit_breaker = _CircuitBreakerState()


def get_circuit_breaker() -> _CircuitBreakerState:
    return _circuit_breaker
