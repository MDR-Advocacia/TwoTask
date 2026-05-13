"""Storage de arquivos de relatorio do Classificador.

Layout no volume persistente (reusa /app/data via PRAZOS_INICIAIS_STORAGE_PATH
parent):
    /app/data/classificador-reports/
        2026/05/13/{uuid4}.xlsx
        2026/05/13/{uuid4}.pdf

O `file_path` gravado em `ClassificadorRelatorio` e' relativo ao root
(`2026/05/13/{uuid}.xlsx`) — mover volume nao precisa de migration.

Em produzao (Coolify) o volume e' `api_data` (externo, blindado).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredReport:
    relative_path: str
    absolute_path: Path
    size_bytes: int
    sha256: str


def _root() -> Path:
    """Diretorio raiz dos relatorios.

    Por simplicidade, reusa o mesmo volume do PI (`prazos_iniciais_storage_path`
    tipicamente `/app/data/prazos-iniciais/...`) e usa um irmao chamado
    `classificador-reports/`. Cai no parent do storage path do PI pra
    ficar no volume montado `/app/data`.
    """
    pi_root = Path(settings.prazos_iniciais_storage_path)
    return pi_root.parent / "classificador-reports"


def save_report(content: bytes, extension: str) -> StoredReport:
    """Grava o relatorio no volume.

    Args:
        content: bytes do arquivo (xlsx ou pdf)
        extension: 'xlsx' | 'pdf' (sem ponto)

    Returns:
        StoredReport com `relative_path` pra persistir em
        `ClassificadorRelatorio.file_path`.
    """
    if not content:
        raise ValueError("Conteudo vazio.")
    if extension not in ("xlsx", "pdf"):
        raise ValueError(f"Extensao invalida: {extension!r}")

    now = datetime.now(timezone.utc)
    rel = Path(
        f"{now:%Y}",
        f"{now:%m}",
        f"{now:%d}",
        f"{uuid.uuid4().hex}.{extension}",
    )
    abs_path = _root() / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    tmp = abs_path.with_suffix(abs_path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(abs_path)

    sha = hashlib.sha256(content).hexdigest()
    logger.info(
        "Classificador report saved: %s (%d bytes, sha=%s…)",
        rel.as_posix(), len(content), sha[:8],
    )
    return StoredReport(
        relative_path=rel.as_posix(),
        absolute_path=abs_path,
        size_bytes=len(content),
        sha256=sha,
    )


def resolve_report_path(relative_path: str) -> Path:
    """Converte path relativo pra absoluto. Valida path traversal."""
    if not relative_path:
        raise ValueError("relative_path vazio.")
    root = _root().resolve()
    candidate = (root / relative_path).resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError(f"Path traversal detectado: {relative_path!r}")
    return candidate
