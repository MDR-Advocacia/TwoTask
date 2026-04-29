"""
Serviço de gestão das contas de sessão AJUS (multi-conta — Chunk 2a).

Responsabilidades:
  - CRUD da tabela `ajus_session_accounts`.
  - Resolução de paths de `storage_state.json` (volume persistente).
  - Transições de status seguras + locks de execução.
  - Submissão do código de IP-auth pelo operador (consumido pelo
    runner — Chunk 2b).
  - Round-robin pra escolha da próxima conta (least-recently-used).

NÃO sabe nada de Playwright — só orquestra estado. O runner (Chunk 2b)
consome essas funções via API HTTP ou diretamente.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ajus import (
    AJUS_ACCOUNT_AGUARDANDO_IP,
    AJUS_ACCOUNT_ERRO,
    AJUS_ACCOUNT_EXECUTANDO,
    AJUS_ACCOUNT_LOGANDO,
    AJUS_ACCOUNT_OFFLINE,
    AJUS_ACCOUNT_ONLINE,
    AJUS_ACCOUNT_STATUSES,
    AjusSessionAccount,
)
from app.services.ajus.crypto import decrypt_password, encrypt_password

logger = logging.getLogger(__name__)


# ─── Path helpers ─────────────────────────────────────────────────────


def _session_root() -> Path:
    return Path(settings.ajus_session_path)


def storage_state_abs_path(account: AjusSessionAccount) -> Path:
    """
    Caminho absoluto do storage_state.json dessa conta. Sempre
    `<root>/<account_id>/storage_state.json` independente do que está
    no campo (que é só pra UI). Resolver pelo ID elimina conflitos
    se admin renomear conta.
    """
    return _session_root() / str(account.id) / "storage_state.json"


def ensure_account_dir(account: AjusSessionAccount) -> Path:
    """Garante que o diretório da conta existe, retorna o caminho."""
    p = _session_root() / str(account.id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def has_storage_state(account: AjusSessionAccount) -> bool:
    return storage_state_abs_path(account).exists()


def delete_storage_state(account: AjusSessionAccount) -> None:
    p = storage_state_abs_path(account)
    try:
        if p.exists():
            os.remove(p)
            logger.info("AJUS session: storage_state apagado pra account %d", account.id)
    except OSError as exc:
        logger.warning(
            "AJUS session: falha apagando storage_state account=%d: %s",
            account.id, exc,
        )


# ─── Service ──────────────────────────────────────────────────────────


class AjusSessionService:
    """CRUD + transições de estado das contas AJUS."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── CRUD ────────────────────────────────────────────────────────

    def list_accounts(
        self, *, only_active: bool = False,
    ) -> list[AjusSessionAccount]:
        q = self.db.query(AjusSessionAccount)
        if only_active:
            q = q.filter(AjusSessionAccount.is_active.is_(True))
        return q.order_by(AjusSessionAccount.id.asc()).all()

    def get_account(self, account_id: int) -> AjusSessionAccount:
        obj = self.db.get(AjusSessionAccount, account_id)
        if obj is None:
            raise ValueError(f"Conta AJUS {account_id} não encontrada.")
        return obj

    def create_account(
        self, *, label: str, login: str, password: str,
    ) -> AjusSessionAccount:
        if not label.strip() or not login.strip() or not password:
            raise ValueError("label, login e password são obrigatórios.")
        # Senha criptografada — falha cedo se Fernet não tá configurada.
        encrypted = encrypt_password(password)
        obj = AjusSessionAccount(
            label=label.strip(),
            login=login.strip(),
            encrypted_password=encrypted,
            status=AJUS_ACCOUNT_OFFLINE,
            is_active=True,
        )
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        # Cria diretório próprio
        ensure_account_dir(obj)
        # Atualiza path nominal (informativo — resolve sempre por ID)
        obj.storage_state_path = f"{obj.id}/storage_state.json"
        self.db.commit()
        self.db.refresh(obj)
        logger.info(
            "AJUS session: conta criada id=%d label=%s login=%s",
            obj.id, obj.label, obj.login,
        )
        return obj

    def update_account(
        self,
        account_id: int,
        *,
        label: Optional[str] = None,
        login: Optional[str] = None,
        password: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> AjusSessionAccount:
        obj = self.get_account(account_id)
        if label is not None:
            obj.label = label.strip()
        if login is not None:
            obj.login = login.strip()
        if password:
            # Trocou senha — invalida storage_state pra forçar re-login.
            obj.encrypted_password = encrypt_password(password)
            delete_storage_state(obj)
            obj.status = AJUS_ACCOUNT_OFFLINE
            obj.pending_ip_code = None
        if is_active is not None:
            obj.is_active = is_active
            if not is_active and obj.status == AJUS_ACCOUNT_EXECUTANDO:
                # Não interrompe execução em curso — só marca pra não
                # ser escolhida em próximos lotes.
                logger.info(
                    "AJUS session: conta %d desativada durante execução; "
                    "seguirá até o fim do batch atual.", obj.id,
                )
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_account(self, account_id: int) -> None:
        obj = self.get_account(account_id)
        if obj.status == AJUS_ACCOUNT_EXECUTANDO:
            raise RuntimeError(
                "Conta está em execução. Aguarde o fim do batch ou "
                "force `is_active=false` antes de deletar.",
            )
        delete_storage_state(obj)
        self.db.delete(obj)
        self.db.commit()
        logger.info("AJUS session: conta %d deletada", account_id)

    def get_password(self, account: AjusSessionAccount) -> str:
        """Decifra senha pra uso pelo runner. Não persiste plaintext."""
        return decrypt_password(account.encrypted_password, account_id=account.id)

    # ── Transições de estado ────────────────────────────────────────

    def set_status(
        self,
        account_id: int,
        new_status: str,
        *,
        error_message: Optional[str] = None,
    ) -> AjusSessionAccount:
        if new_status not in AJUS_ACCOUNT_STATUSES:
            raise ValueError(f"Status inválido: {new_status}")
        obj = self.get_account(account_id)
        obj.status = new_status
        if new_status == AJUS_ACCOUNT_ERRO:
            obj.last_error_message = (error_message or "Sem detalhes.")[:4000]
            obj.last_error_at = datetime.now(timezone.utc)
        elif new_status == AJUS_ACCOUNT_ONLINE:
            obj.last_error_message = None
            obj.last_error_at = None
            obj.pending_ip_code = None
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def submit_ip_code(self, account_id: int, code: str) -> AjusSessionAccount:
        """
        Operador submete o código de validação de IP via UI. Runner
        (no outro container) faz polling em `pending_ip_code` e
        consome quando estiver no flow de login.
        """
        if not code or not code.strip():
            raise ValueError("Código vazio.")
        obj = self.get_account(account_id)
        if obj.status != AJUS_ACCOUNT_AGUARDANDO_IP:
            raise RuntimeError(
                f"Conta não está aguardando código (status atual: {obj.status}).",
            )
        obj.pending_ip_code = code.strip()
        self.db.commit()
        self.db.refresh(obj)
        logger.info("AJUS session: IP-code submetido pra account %d", account_id)
        return obj

    def clear_ip_code(self, account_id: int) -> AjusSessionAccount:
        """Runner consumiu o código (sucesso ou expirou)."""
        obj = self.get_account(account_id)
        obj.pending_ip_code = None
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def request_login(self, account_id: int) -> AjusSessionAccount:
        """
        Operador clica 'Login' na UI — marca conta como `logando` pra
        que o runner (polling) inicie o flow.
        """
        obj = self.get_account(account_id)
        if obj.status == AJUS_ACCOUNT_EXECUTANDO:
            raise RuntimeError(
                "Conta está executando um batch — aguarde antes de relogar.",
            )
        delete_storage_state(obj)  # força fresh login
        obj.status = AJUS_ACCOUNT_LOGANDO
        obj.pending_ip_code = None
        obj.last_error_message = None
        obj.last_error_at = None
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def request_logout(self, account_id: int) -> AjusSessionAccount:
        obj = self.get_account(account_id)
        if obj.status == AJUS_ACCOUNT_EXECUTANDO:
            raise RuntimeError(
                "Conta está executando — não pode encerrar sessão agora.",
            )
        delete_storage_state(obj)
        obj.status = AJUS_ACCOUNT_OFFLINE
        obj.pending_ip_code = None
        self.db.commit()
        self.db.refresh(obj)
        return obj

    # ── Round-robin pro dispatcher (Chunk 2c) ───────────────────────

    def claim_for_run(self) -> Optional[AjusSessionAccount]:
        """
        Pega a próxima conta `online` ativa (least-recently-used) e
        marca como `executando`. Retorna None se nenhuma disponível.

        Atomic-ish: busca + update no mesmo commit. Concorrência fina
        é via lock advisory do Postgres (Chunk 2c se virar gargalo).
        """
        candidate = (
            self.db.query(AjusSessionAccount)
            .filter(
                AjusSessionAccount.is_active.is_(True),
                AjusSessionAccount.status == AJUS_ACCOUNT_ONLINE,
            )
            .order_by(
                AjusSessionAccount.last_used_at.asc().nulls_first(),
                AjusSessionAccount.id.asc(),
            )
            .with_for_update(skip_locked=True)
            .first()
        )
        if candidate is None:
            return None
        candidate.status = AJUS_ACCOUNT_EXECUTANDO
        candidate.last_used_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def release_run(
        self,
        account_id: int,
        *,
        had_error: bool = False,
        error_message: Optional[str] = None,
    ) -> AjusSessionAccount:
        """
        Runner terminou o batch — devolve conta pra `online` (ou `erro`
        se algo crítico aconteceu, ex.: sessão expirou no meio).
        """
        obj = self.get_account(account_id)
        if had_error:
            obj.status = AJUS_ACCOUNT_ERRO
            obj.last_error_message = (error_message or "Sem detalhes.")[:4000]
            obj.last_error_at = datetime.now(timezone.utc)
        else:
            obj.status = AJUS_ACCOUNT_ONLINE
        self.db.commit()
        self.db.refresh(obj)
        return obj
