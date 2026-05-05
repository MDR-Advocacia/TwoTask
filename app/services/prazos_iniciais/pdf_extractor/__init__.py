"""
Motor de extração mecânica de PDFs de processos judiciais.

Fluxo USER_UPLOAD: operador sobe o PDF do processo na íntegra; este
módulo lê o texto via pdfplumber, detecta o template (PJe TJBA por
enquanto), aplica limpeza mecânica (boilerplate repetido, marcadores
de página, carimbos de assinatura) e monta `capa_json` + `integra_json`
no formato esperado pelo motor de classificação.

Sem IA aqui — a estruturação é 100% por regex/heurística. O que não
der pra capturar mecanicamente fica `null` na capa e o motor de
classificação principal preenche depois.

Estrutura:
    extract(pdf_bytes) -> ExtractionResult
        |
        ├── text_extractor.py        (pdfplumber → list[str] por página)
        ├── template_detector.py     (escolhe extractor)
        ├── cleaner.py               (regex de limpeza compartilhadas)
        └── extractors/
            ├── pje_tjba.py          (capa + timeline do PJe TJBA)
            └── fallback.py          (texto cru, sem estruturação)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.prazos_iniciais.pdf_extractor.template_detector import (
    detect_template,
)
from app.services.prazos_iniciais.pdf_extractor.text_extractor import (
    PdfTextExtractionError,
    extract_text_pages,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    """
    Resultado da extração mecânica.

    Atributos:
        success: True se extraiu texto E pelo menos um extractor rodou.
                 False = PDF sem texto (escaneado) → operador classifica
                 manualmente no HITL.
        extractor_used: identificador do extractor (ex.: "pje_tjba_v1",
                        "fallback_text"). None se PDF sem texto.
        confidence: "high" / "partial" / "low". None se PDF sem texto.
        capa_json: dict no formato esperado pelo intake (pode estar vazio
                   ou parcial — campos não capturáveis ficam null).
        integra_json: dict com a íntegra estruturada (timeline para PJe;
                      texto cru para fallback).
        cnj_number: CNJ extraído da capa via regex (None se não achou).
        error_message: mensagem traduzida pra UI quando success=False.
    """

    success: bool
    extractor_used: Optional[str]
    confidence: Optional[str]
    capa_json: dict = field(default_factory=dict)
    integra_json: dict = field(default_factory=dict)
    cnj_number: Optional[str] = None
    error_message: Optional[str] = None


def extract(pdf_bytes: bytes) -> ExtractionResult:
    """
    Tenta extrair capa + integra de um PDF de processo judicial.

    Nunca levanta — falhas viram `success=False` com `error_message`
    traduzido pro operador.
    """
    # 1. Texto cru por página.
    try:
        pages = extract_text_pages(pdf_bytes)
    except PdfTextExtractionError as exc:
        logger.warning("Falha ao abrir PDF com pdfplumber: %s", exc)
        return ExtractionResult(
            success=False,
            extractor_used=None,
            confidence=None,
            error_message=str(exc),
        )

    # PDF aberto mas sem texto extraível (escaneado/imagem-only).
    total_chars = sum(len(p) for p in pages)
    if total_chars < 50:
        return ExtractionResult(
            success=False,
            extractor_used=None,
            confidence=None,
            error_message=(
                "Não foi possível extrair texto deste PDF "
                "(provavelmente é digitalizado/escaneado). "
                "O processo foi cadastrado mesmo assim — você pode "
                "classificar manualmente na tela de tratamento."
            ),
        )

    # 2. Escolhe extractor pelo template detectado.
    extractor = detect_template(pages)
    logger.info("PDF extractor selecionado: %s", extractor.name)

    # 3. Roda o extractor.
    try:
        return extractor.extract(pages)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Extractor %s falhou — caindo no fallback.", extractor.name)
        # Em caso de erro inesperado no extractor específico, devolve o
        # texto cru concatenado pra não perder o conteúdo.
        from app.services.prazos_iniciais.pdf_extractor.extractors.fallback import (
            FallbackExtractor,
        )

        return FallbackExtractor().extract(pages)


__all__ = ["ExtractionResult", "extract"]
