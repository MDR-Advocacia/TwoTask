"""Webhook callback do Classificador — notifica URL externa quando
lote vira CLASSIFICADO.

Pattern fire-and-forget com retry:
- Payload assinado por HMAC-SHA256 (header X-Classificador-Signature).
- Retries: 3 tentativas (backoff 5s, 30s, 2min).
- Timeout: 10s por tentativa.
- Log de cada tentativa + falha terminal (sem table de log nessa versao).

Disparado por `classifier_runner.apply_batch_results` quando lote
transiciona pra CLASSIFICADO.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.classificador import ClassificadorLote

logger = logging.getLogger(__name__)


# Backoffs por tentativa (segundos)
_BACKOFF_SCHEDULE = [5, 30, 120]


def _build_payload(lote: ClassificadorLote) -> dict[str, Any]:
    """Constroi payload JSON do webhook a partir do ClassificadorLote."""
    def _f(v):
        return float(v) if v is not None else None

    return {
        "event": "classificador.lote.classified",
        "lote_id": lote.id,
        "lote_nome": lote.nome,
        "cliente_nome": lote.cliente_nome,
        "status": lote.status,
        "total_processos": lote.total_processos or 0,
        "total_classificados": lote.total_processos_classificados or 0,
        "total_com_erro": lote.total_processos_com_erro or 0,
        "valor_total_estimado": _f(lote.valor_total_estimado),
        "valor_total_causa": _f(lote.valor_total_causa),
        "pcond_total": _f(lote.pcond_total),
        "prob_exito_medio": _f(lote.prob_exito_medio),
        "classificacao_finished_at": (
            lote.classificacao_finished_at.isoformat()
            if lote.classificacao_finished_at else None
        ),
        "created_at": lote.created_at.isoformat() if lote.created_at else None,
        "snapshot_at": lote.snapshot_at.isoformat() if lote.snapshot_at else None,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }


def _sign_payload(body: bytes, secret: str) -> str:
    """HMAC-SHA256 hex digest. Cliente valida igualdade tempo-constante."""
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _send_sync(payload: dict, url: str, secret: str | None) -> None:
    """Envia o webhook com retry + backoff (sincrono, rodado em thread)."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Classificador-Signature"] = _sign_payload(body, secret)

    max_retries = settings.classificador_webhook_max_retries
    timeout = settings.classificador_webhook_timeout_seconds

    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, content=body, headers=headers)
            if 200 <= resp.status_code < 300:
                logger.info(
                    "webhook OK lote=%s attempt=%d status=%d",
                    payload.get("lote_id"), attempt, resp.status_code,
                )
                return
            logger.warning(
                "webhook lote=%s attempt=%d status=%d body=%s",
                payload.get("lote_id"), attempt, resp.status_code,
                resp.text[:200],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "webhook lote=%s attempt=%d erro=%s",
                payload.get("lote_id"), attempt, exc,
            )

        # Backoff antes da próxima tentativa
        if attempt < max_retries:
            backoff = _BACKOFF_SCHEDULE[min(attempt - 1, len(_BACKOFF_SCHEDULE) - 1)]
            time.sleep(backoff)

    logger.error(
        "webhook lote=%s FALHOU apos %d tentativas",
        payload.get("lote_id"), max_retries,
    )


def send_lote_classified_webhook(lote_id: int) -> None:
    """Dispara webhook em thread separada (fire-and-forget).

    NAO bloqueia o fluxo do classifier_runner — chamada returna
    imediatamente, retries acontecem em background.

    Se URL nao configurada, no-op.
    """
    url = settings.classificador_webhook_url
    if not url:
        return

    db = SessionLocal()
    try:
        lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
        if not lote:
            logger.warning("webhook: lote #%s nao encontrado", lote_id)
            return
        payload = _build_payload(lote)
    finally:
        db.close()

    # Roda em thread daemon — nao trava shutdown se webhook tiver retry pendente
    thread = threading.Thread(
        target=_send_sync,
        args=(payload, url, settings.classificador_webhook_secret),
        name=f"webhook-lote-{lote_id}",
        daemon=True,
    )
    thread.start()
    logger.info(
        "webhook lote=%s disparado (async, ate %d retries)",
        lote_id, settings.classificador_webhook_max_retries,
    )
