"""
Extractor pra PDFs do eSAJ (TJSP, TJMS, TJSC parcial, TJBA parcial...).

DIFERENTE de PJe/eproc/PROJUDI, o "Salvar PDF do processo" do eSAJ
NÃO inclui uma página de capa estruturada — os documentos são
concatenados direto, com metadados aparecendo apenas na barra lateral
de validação (texto rotacionado 180°, lido invertido pelo pdfplumber).

Por consequência, este extractor entrega:
  - CNJ (regex direto, do nome ou de uma das ocorrências no texto)
  - Tribunal (derivado do CNJ)
  - integra_json com texto cru (capa fica vazia)
  - confidence: `partial` quando achou CNJ; `low` caso contrário.

O motor de classificação principal preenche os campos da capa
(classe, vara, partes, valor) a partir da própria petição inicial.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from app.services.prazos_iniciais.pdf_extractor.extractors.base import (
    BaseExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.tribunais import tribunal_from_cnj

logger = logging.getLogger(__name__)


# CNJ no formato com máscara
_RE_CNJ = re.compile(r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})")


class EsajExtractor(BaseExtractor):
    name = "esaj_v1"

    def extract(self, pages: List[str]):
        from app.services.prazos_iniciais.pdf_extractor import ExtractionResult

        full_text = "\n".join(pages)
        cnj = _extract_cnj(full_text)
        tribunal = tribunal_from_cnj(cnj) if cnj else None

        capa: dict = {}
        if tribunal:
            capa["tribunal"] = tribunal

        # Texto cru (sem timeline estruturada — o motor de classificação
        # consome direto). Mantém os primeiros ~30k caracteres pra evitar
        # estourar limites do classificador em PDFs muito grandes.
        # (Truncagem é segura porque a petição inicial costuma estar nas
        # primeiras dezenas de páginas; documentos posteriores entram
        # como contexto auxiliar quando couber.)
        MAX_INTEGRA_CHARS = 200_000
        texto = full_text[:MAX_INTEGRA_CHARS] if len(full_text) > MAX_INTEGRA_CHARS else full_text

        confidence = "partial" if cnj else "low"

        return ExtractionResult(
            success=True,
            extractor_used=self.name,
            confidence=confidence,
            capa_json=capa,
            integra_json={"texto_cru": texto},
            cnj_number=cnj,
        )


def _extract_cnj(text: str) -> Optional[str]:
    """
    eSAJ não tem capa formal — o texto pode mencionar vários CNJs
    (precedentes, referências cruzadas). O CNJ do processo principal
    é o que aparece com mais frequência. Em caso de empate, escolhe
    o que aparece primeiro.
    """
    from collections import Counter

    matches = _RE_CNJ.findall(text)
    if not matches:
        return None
    counter = Counter(matches)
    # `most_common` preserva ordem de inserção em caso de empate (Python 3.7+)
    return counter.most_common(1)[0][0]
