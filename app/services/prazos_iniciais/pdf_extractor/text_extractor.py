"""Wrapper fino sobre pdfplumber pra extrair texto por página."""

from __future__ import annotations

import io
import logging
from typing import List

logger = logging.getLogger(__name__)


class PdfTextExtractionError(Exception):
    """PDF inválido, criptografado ou corrompido."""


def extract_text_pages(pdf_bytes: bytes) -> List[str]:
    """
    Abre o PDF em memória e devolve uma lista de strings — uma por
    página. Páginas em branco viram strings vazias.

    Raises:
        PdfTextExtractionError — se o PDF não puder ser aberto.
    """
    if not pdf_bytes:
        raise PdfTextExtractionError("PDF vazio.")

    try:
        import pdfplumber
    except ImportError as exc:
        raise PdfTextExtractionError(
            "pdfplumber não está instalado no ambiente."
        ) from exc

    pages: List[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                try:
                    text = page.extract_text() or ""
                except Exception:  # noqa: BLE001
                    # Falha por página não derruba a extração toda.
                    logger.warning(
                        "Falha ao extrair texto da página %s — pulando.",
                        getattr(page, "page_number", "?"),
                    )
                    text = ""
                pages.append(text)
    except Exception as exc:  # noqa: BLE001
        raise PdfTextExtractionError(
            f"Não foi possível abrir o PDF: {exc}"
        ) from exc

    return pages
