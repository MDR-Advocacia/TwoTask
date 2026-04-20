"""
Armazenamento local dos PDFs de habilitação do fluxo "Agendar Prazos Iniciais".

Os PDFs vivem em um volume persistente do container da API até serem
enviados ao GED (ECM) do Legal One. Após a confirmação do upload e o
período de retenção configurado, um job faz cleanup e zera `pdf_path`
na tabela `prazo_inicial_intakes`.

Layout de diretórios:
    {PRAZOS_INICIAIS_STORAGE_PATH}/
        2026/
            04/
                20/
                    {uuid4}.pdf

O caminho gravado em `PrazoInicialIntake.pdf_path` é **relativo** à raiz
(`2026/04/20/{uuid}.pdf`) — isso permite mover o volume sem reescrever
a coluna.
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

# Magic bytes — valida que o arquivo é realmente um PDF, independente
# do Content-Type declarado pelo cliente.
PDF_MAGIC = b"%PDF"


class PdfValidationError(ValueError):
    """Arquivo recebido não é um PDF válido ou excede o tamanho permitido."""


@dataclass(frozen=True)
class StoredPdf:
    """Metadados de um PDF gravado no volume local."""

    relative_path: str  # "2026/04/20/abc.pdf" — gravado em pdf_path
    absolute_path: Path  # caminho absoluto resolvido
    size_bytes: int
    sha256: str


def _root() -> Path:
    return Path(settings.prazos_iniciais_storage_path)


def validate_pdf_bytes(pdf_bytes: bytes) -> None:
    """
    Valida que o conteúdo é um PDF e está dentro do limite configurado.
    Lança PdfValidationError com mensagem descritiva em caso de falha.
    """
    if not pdf_bytes:
        raise PdfValidationError("PDF vazio.")

    if not pdf_bytes.startswith(PDF_MAGIC):
        raise PdfValidationError(
            "Arquivo não é um PDF válido (magic bytes '%PDF' ausentes)."
        )

    size = len(pdf_bytes)
    max_bytes = settings.prazos_iniciais_max_pdf_bytes
    if size > max_bytes:
        raise PdfValidationError(
            f"PDF excede o tamanho máximo permitido "
            f"({size} bytes > {max_bytes} bytes / "
            f"{settings.prazos_iniciais_max_pdf_mb} MB)."
        )


def save_pdf(pdf_bytes: bytes, *, now: datetime | None = None) -> StoredPdf:
    """
    Valida e grava o PDF no volume persistente.

    O nome do arquivo é um UUID4 para evitar colisões e não depender do
    nome original enviado pelo cliente (que guardamos em
    `pdf_filename_original` apenas para auditoria/UI).

    Raises:
        PdfValidationError — se o conteúdo não passa na validação.
        OSError — se a gravação no disco falhar.
    """
    validate_pdf_bytes(pdf_bytes)

    timestamp = now or datetime.now(timezone.utc)
    relative = Path(
        f"{timestamp:%Y}",
        f"{timestamp:%m}",
        f"{timestamp:%d}",
        f"{uuid.uuid4().hex}.pdf",
    )
    absolute = _root() / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)

    # Grava primeiro num arquivo temporário e faz rename atômico — evita
    # que um crash a meio caminho deixe arquivos truncados no volume.
    tmp = absolute.with_suffix(".pdf.tmp")
    tmp.write_bytes(pdf_bytes)
    tmp.replace(absolute)

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    logger.info(
        "PDF gravado: %s (%d bytes, sha256=%s…)",
        relative.as_posix(),
        len(pdf_bytes),
        sha256[:8],
    )

    return StoredPdf(
        relative_path=relative.as_posix(),
        absolute_path=absolute,
        size_bytes=len(pdf_bytes),
        sha256=sha256,
    )


def resolve_pdf_path(relative_path: str) -> Path:
    """
    Converte o `pdf_path` relativo (como gravado na tabela) para um
    caminho absoluto dentro do volume. Valida contra path-traversal.
    """
    root = _root().resolve()
    candidate = (root / relative_path).resolve()
    # Garante que o caminho resolvido não escapa da raiz.
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"Caminho inválido (fora da raiz): {relative_path}")
    return candidate


def delete_pdf(relative_path: str) -> bool:
    """
    Remove o PDF do volume. Retorna True se apagou, False se o arquivo
    não existia (no-op seguro).
    """
    try:
        path = resolve_pdf_path(relative_path)
    except ValueError:
        logger.warning("delete_pdf chamado com caminho inválido: %s", relative_path)
        return False

    if not path.exists():
        return False

    path.unlink()
    # Best-effort: tenta limpar diretórios vazios subindo a árvore.
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
