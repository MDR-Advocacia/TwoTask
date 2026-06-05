"""Armazenamento local dos arquivos enviados pro GED do Legal One.

Diferente do storage de prazos_iniciais (PDF-only, valida magic %PDF),
aqui aceitamos qualquer extensao da allow-list (pdf, docx, xlsx, imagens...)
porque o GED do L1 e' generico. Os arquivos vivem num volume persistente
ate o upload no GED; depois que o lote termina (ou e' deletado), o cleanup
os remove.

Layout:
    {GED_LEGALONE_STORAGE_PATH}/YYYY/MM/DD/{uuid}.{ext}

O path gravado em `ged_upload_item.file_path` / `ged_upload_batch.shared_file_path`
e' RELATIVO a raiz — permite mover o volume sem reescrever a coluna.
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


class FileValidationError(ValueError):
    """Arquivo recebido viola tamanho ou extensao permitida."""


@dataclass(frozen=True)
class StoredFile:
    """Metadados de um arquivo gravado no volume local."""

    relative_path: str   # "2026/06/04/abc.docx" — gravado em file_path
    absolute_path: Path
    size_bytes: int
    sha256: str


def _root() -> Path:
    return Path(settings.ged_legalone_storage_path)


def normalize_ext(filename_or_ext: str | None) -> str:
    """
    Extrai/normaliza a extensao (sem ponto, lowercase). Aceita tanto
    "arquivo.DOCX" quanto "docx" quanto ".pdf". Retorna "" se nao houver.
    """
    if not filename_or_ext:
        return ""
    base = str(filename_or_ext)
    ext = base.rsplit(".", 1)[-1] if "." in base else base
    return ext.strip().lower().lstrip(".")


def validate_file_bytes(file_bytes: bytes, ext: str) -> None:
    """
    Valida tamanho + extensao na allow-list. Levanta FileValidationError
    com mensagem voltada ao operador.
    """
    if not file_bytes:
        raise FileValidationError("Arquivo vazio.")

    norm = normalize_ext(ext)
    allowed = settings.ged_legalone_allowed_extensions_set
    if norm not in allowed:
        raise FileValidationError(
            f"Extensao '.{norm or '?'}' nao permitida. "
            f"Aceitas: {', '.join(sorted(allowed))}."
        )

    size = len(file_bytes)
    max_bytes = settings.ged_legalone_max_file_bytes
    if size > max_bytes:
        raise FileValidationError(
            f"Arquivo excede o tamanho maximo "
            f"({size} bytes > {max_bytes} bytes / "
            f"{settings.ged_legalone_max_file_mb} MB)."
        )


def save_file(
    file_bytes: bytes, *, ext: str, now: datetime | None = None
) -> StoredFile:
    """
    Valida e grava o arquivo no volume. Nome = UUID4, extensao preservada
    (importante: o L1 valida a extensao do `archive` no POST /documents).

    Raises:
        FileValidationError — se o conteudo nao passa na validacao.
        OSError — se a gravacao no disco falhar.
    """
    norm = normalize_ext(ext) or "bin"
    validate_file_bytes(file_bytes, norm)

    timestamp = now or datetime.now(timezone.utc)
    relative = Path(
        f"{timestamp:%Y}",
        f"{timestamp:%m}",
        f"{timestamp:%d}",
        f"{uuid.uuid4().hex}.{norm}",
    )
    absolute = _root() / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)

    # Grava num temp e faz rename atomico — crash a meio caminho nao deixa
    # arquivo truncado no volume.
    tmp = absolute.with_suffix(absolute.suffix + ".tmp")
    tmp.write_bytes(file_bytes)
    tmp.replace(absolute)

    sha256 = hashlib.sha256(file_bytes).hexdigest()
    logger.info(
        "GED LegalOne: arquivo gravado %s (%d bytes, sha256=%s...)",
        relative.as_posix(),
        len(file_bytes),
        sha256[:8],
    )

    return StoredFile(
        relative_path=relative.as_posix(),
        absolute_path=absolute,
        size_bytes=len(file_bytes),
        sha256=sha256,
    )


def resolve_file_path(relative_path: str) -> Path:
    """Relativo -> absoluto dentro do volume, com guard de path-traversal."""
    root = _root().resolve()
    candidate = (root / relative_path).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"Caminho invalido (fora da raiz): {relative_path}")
    return candidate


def delete_file(relative_path: str) -> bool:
    """
    Remove o arquivo do volume. Retorna True se apagou, False se nao
    existia (no-op seguro). Importante no modo SINGLE_FILE: o mesmo path
    e' referenciado por N itens — o chamador deve deduplicar antes de
    chamar (cada path 1x), mas chamar 2x e' inofensivo.
    """
    if not relative_path:
        return False
    try:
        path = resolve_file_path(relative_path)
    except ValueError:
        logger.warning("delete_file: caminho invalido: %s", relative_path)
        return False

    if not path.exists():
        return False

    path.unlink()
    # best-effort: limpa diretorios vazios subindo a arvore.
    parent = path.parent
    root = _root().resolve()
    for _ in range(3):
        if parent == root:
            break
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return True
