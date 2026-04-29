"""
Criptografia de senhas das contas AJUS — Fernet (symmetric).

Por que Fernet:
  - Já vem como dependência transitiva de `python-jose[cryptography]`
    (sem subir requisito novo).
  - Symmetric e suficiente pra esse caso (operador escreve, runner lê).
  - Token base64 ASCII — seguro pra armazenar como TEXT no Postgres.

Chave:
  - Lida de `AJUS_FERNET_KEY` (env). Deve ser uma key Fernet válida
    (32 bytes urlsafe-base64-encoded). Gera com:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  - Sem chave configurada → operações falham com erro claro. NÃO faz
    fallback silencioso (criptografar com chave vazia ou plaintext —
    seria pior do que falhar).

Logs:
  - NUNCA logam plaintext nem token decifrado. Erros logam só o
    `account_id` e tipo do erro.
"""

from __future__ import annotations

import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)


class AjusCryptoError(RuntimeError):
    """Falha de configuração ou de descriptografia."""


def _get_cipher() -> Fernet:
    """
    Resolve o cipher Fernet. Lê `settings.ajus_fernet_key` (lazy —
    permite testes setarem a key antes do primeiro uso).
    """
    key: Optional[str] = getattr(settings, "ajus_fernet_key", None)
    if not key:
        raise AjusCryptoError(
            "AJUS_FERNET_KEY não configurada. Gere uma key com "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` e adicione ao .env "
            "(ou ao painel do Coolify).",
        )
    try:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise AjusCryptoError(
            f"AJUS_FERNET_KEY inválida (deve ser 32 bytes urlsafe-base64): "
            f"{exc}",
        ) from exc


def encrypt_password(plaintext: str) -> str:
    """Criptografa senha. Retorna token base64 ASCII (TEXT-safe)."""
    if not plaintext:
        raise ValueError("Senha vazia.")
    cipher = _get_cipher()
    token = cipher.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_password(token: str, *, account_id: Optional[int] = None) -> str:
    """
    Decifra token. Logs identificam só `account_id` em caso de erro —
    nunca expõem plaintext nem o token.
    """
    if not token:
        raise ValueError("Token vazio.")
    cipher = _get_cipher()
    try:
        plain = cipher.decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        logger.error(
            "AJUS crypto: token inválido pra account_id=%s — chave Fernet "
            "pode ter sido rotacionada. Recadastre a senha.",
            account_id,
        )
        raise AjusCryptoError(
            "Token Fernet inválido — chave pode ter sido rotacionada. "
            "Recadastre a senha da conta.",
        ) from exc
    return plain.decode("utf-8")


def is_configured() -> bool:
    """Helper pra UI / health-check: chave está setada e válida?"""
    try:
        _get_cipher()
        return True
    except AjusCryptoError:
        return False
