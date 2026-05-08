"""Helper de extracao + normalizacao de texto pra validacao."""

from __future__ import annotations

import re
import unicodedata
from typing import List


def extract_pages(pdf_bytes: bytes) -> List[str]:
    """Extrai texto por pagina reusando o motor pdfplumber existente."""
    from app.services.prazos_iniciais.pdf_extractor.text_extractor import (
        extract_text_pages,
    )

    return extract_text_pages(pdf_bytes)


def join_pages(pages: List[str]) -> str:
    """Concatena paginas com separador, preservando ordem."""
    return "\n\n".join(p for p in pages if p)


def normalize(text: str) -> str:
    """
    Normaliza texto pra matching robusto: remove acentos, lowercase,
    colapsa whitespace. Garante que matches funcionem mesmo com quebras
    de linha estranhas, caracteres invisiveis ou variacoes de
    capitalizacao no PDF.
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = no_accents.lower()
    collapsed = re.sub(r"\s+", " ", lower)
    return collapsed.strip()


def normalize_marker(marker: str) -> str:
    """
    Normaliza uma string de marcador (ancora/nome/oab) pra comparar
    contra texto ja normalizado. Equivalente a normalize() mas sem
    colapsar whitespace (markers nao tem newlines).
    """
    if not marker:
        return ""
    nfkd = unicodedata.normalize("NFKD", marker)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_accents.lower()
