"""Persistencia do XLSX original em volume.

Naming determinista por sha256 do conteudo — reupload de XLSX identico
nao gasta espaco (idempotente).

Default: $BASE_PROCESSUAL_STORAGE_DIR ou /data/base-processual/uploads/.
Em dev (sem volume), usa data/base-processual/uploads relativo ao projeto.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional


_DEFAULT_DIR = "/data/base-processual/uploads"


def get_storage_dir() -> Path:
    base = os.environ.get("BASE_PROCESSUAL_STORAGE_DIR", _DEFAULT_DIR)
    path = Path(base)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        # fallback pra ./data/... em dev (sem volume montado)
        fallback = Path.cwd() / "data" / "base-processual" / "uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    return path


def save_xlsx(content: bytes) -> tuple[str, str]:
    """Salva XLSX em disco. Idempotente por sha do conteudo.

    Retorna (storage_path_absoluto, sha256_hex).
    """
    sha = hashlib.sha256(content).hexdigest()
    target = get_storage_dir() / f"{sha}.xlsx"
    if not target.exists():
        target.write_bytes(content)
    return str(target), sha


def read_xlsx(storage_path: str) -> bytes:
    return Path(storage_path).read_bytes()


def delete_xlsx(storage_path: Optional[str]) -> None:
    if not storage_path:
        return
    try:
        Path(storage_path).unlink(missing_ok=True)
    except OSError:
        pass
