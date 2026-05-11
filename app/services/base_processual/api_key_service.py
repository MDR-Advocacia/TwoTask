"""Geracao, verificacao e rate-limit das API keys externas (Chunk 6).

Formato da key plaintext: 'bpk_<32 chars>'. Armazenamos:
- key_hash: sha256(plaintext) — UNIQUE no banco
- key_prefix: primeiros 12 chars (bpk_xxxxxxxx) — visivel na UI pra
  identificar a chave sem expor o resto

Plaintext e' mostrado UMA UNICA VEZ na resposta do POST/regenerate.
Operador copia, salva em local seguro, e pronto — nao tem recuperacao.

Rate limit: in-memory por worker (dict simples). v2 = Redis pra
distribuir entre workers do Uvicorn.

Scopes:
- read_processos: lista/get processos sem campos de valor
- read_valores: include money fields
- read_dashboard: endpoints /dashboard/*
- read_all: tudo (super-scope)
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.base_processual import BaseProcessualApiKey


PUBLIC_KEY_PREFIX = "bpk_"

SCOPE_READ_PROCESSOS = "read_processos"
SCOPE_READ_VALORES = "read_valores"
SCOPE_READ_DASHBOARD = "read_dashboard"
SCOPE_READ_ALL = "read_all"

VALID_SCOPES = (
    SCOPE_READ_PROCESSOS,
    SCOPE_READ_VALORES,
    SCOPE_READ_DASHBOARD,
    SCOPE_READ_ALL,
)


def generate_key() -> tuple[str, str, str]:
    """Gera (plaintext, prefix, hash). Plaintext nunca persiste."""
    body = secrets.token_urlsafe(32)
    plaintext = f"{PUBLIC_KEY_PREFIX}{body}"
    prefix = plaintext[:12]
    key_hash = hash_key(plaintext)
    return plaintext, prefix, key_hash


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def find_active_by_plaintext(
    db: Session, plaintext: str
) -> Optional[BaseProcessualApiKey]:
    """Lookup por hash (sha256). Retorna None se revogada."""
    if not plaintext:
        return None
    h = hash_key(plaintext)
    return (
        db.query(BaseProcessualApiKey)
        .filter(BaseProcessualApiKey.key_hash == h)
        .filter(BaseProcessualApiKey.revoked_at.is_(None))
        .first()
    )


def has_scope(key: BaseProcessualApiKey, *allowed: str) -> bool:
    """True se a chave tem `read_all` OU um dos `allowed`."""
    if key.scope == SCOPE_READ_ALL:
        return True
    return key.scope in allowed


# ============================================================================
# Rate limiter in-memory (por worker do uvicorn).
# ============================================================================

_RATE_BUCKETS: dict[int, list[float]] = {}
_RATE_LOCK = threading.Lock()
_RATE_WINDOW_SECONDS = 60.0


def check_rate_limit(key: BaseProcessualApiKey) -> tuple[bool, int]:
    """Retorna (allowed, remaining). True se a request pode prosseguir.

    Sliding window de 60s: mantem timestamps das requests nesse range
    e compara com key.rate_limit_per_min.
    """
    now = time.monotonic()
    cap = max(1, int(key.rate_limit_per_min or 60))
    with _RATE_LOCK:
        bucket = _RATE_BUCKETS.setdefault(key.id, [])
        # purga timestamps fora da janela
        bucket[:] = [t for t in bucket if (now - t) < _RATE_WINDOW_SECONDS]
        if len(bucket) >= cap:
            return False, 0
        bucket.append(now)
        return True, max(0, cap - len(bucket))


def reset_rate_limit_for_key(key_id: int) -> None:
    """Pra usar em testes. Em prod nao usamos."""
    with _RATE_LOCK:
        _RATE_BUCKETS.pop(key_id, None)


def touch_last_used(db: Session, key: BaseProcessualApiKey) -> None:
    """Atualiza last_used_at sem bloquear demais.

    V1: commit a cada hit. Pra QPS alto isso e' caro — em v2 jogar
    pra um worker batched (LIFO buffer + flush periodico).
    """
    key.last_used_at = datetime.utcnow()
    db.commit()
