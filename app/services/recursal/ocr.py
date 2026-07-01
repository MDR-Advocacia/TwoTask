"""
OCR dos documentos-IMAGEM (escaneados/foto) do processo.

O extractor mecânico (pdfplumber) não lê imagem, então documento escaneado
sai sem texto. Aqui rodamos Tesseract SÓ nas páginas que saíram sem texto —
não no PDF inteiro. Capado (nº de páginas + chars) pra não estourar tempo de
upload nem token. Tesseract é local (grátis, sem taxa por página).

Degradação graciosa: se pymupdf/pytesseract/o binário tesseract não estiverem
disponíveis (imagem Docker ainda não reconstruída), retorna [] e o fluxo
segue com o manifesto de documentos.
"""

from __future__ import annotations

import io
import logging
from typing import List

logger = logging.getLogger(__name__)

# Página com menos que isso de texto = imagem (candidata a OCR).
_MIN_TEXT_CHARS = 20
# Resolução de render pro OCR (equilíbrio qualidade x tempo).
_DPI = 220


def ocr_paginas_imagem(
    pdf_bytes: bytes,
    max_pages: int = 15,
    max_chars: int = 18_000,
) -> List[dict]:
    """
    Roda OCR apenas nas páginas SEM texto (imagem/escaneado) do PDF.

    Retorna lista de {"pagina": int, "texto": str}, capada por max_pages e
    max_chars. [] se OCR indisponível ou nada a fazer.
    """
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        logger.info("OCR indisponível (dependências ausentes): %s", exc)
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR: falha ao abrir PDF: %s", exc)
        return []

    out: List[dict] = []
    total = 0
    try:
        for i in range(doc.page_count):
            if len(out) >= max_pages or total >= max_chars:
                break
            page = doc.load_page(i)
            texto = (page.get_text() or "").strip()
            if len(texto) >= _MIN_TEXT_CHARS:
                continue  # página já tem texto — pdfplumber já pegou
            if not page.get_images():
                continue  # sem texto e sem imagem = página em branco
            try:
                pix = page.get_pixmap(dpi=_DPI)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr = (pytesseract.image_to_string(img, lang="por") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("OCR falhou na página %d: %s", i + 1, exc)
                continue
            if not ocr:
                continue
            ocr = ocr[: max(0, max_chars - total)]
            out.append({"pagina": i + 1, "texto": ocr})
            total += len(ocr)
    finally:
        doc.close()

    logger.info(
        "OCR recursal: %d página(s)-imagem recuperada(s) (%d chars).",
        len(out), total,
    )
    return out
