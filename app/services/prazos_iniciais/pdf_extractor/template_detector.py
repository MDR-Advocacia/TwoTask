"""
Decide qual extractor rodar pra um conjunto de páginas.

Hoje só existe PJe TJBA + fallback. Quando aparecerem exemplos de eSAJ
(TJSP), ProJudi, etc., adicionar mais condições aqui — o resto do
pipeline não precisa mudar.
"""

from __future__ import annotations

import re
from typing import List

from app.services.prazos_iniciais.pdf_extractor.extractors.base import (
    BaseExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.fallback import (
    FallbackExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.pje_tjba import (
    PjeTjbaExtractor,
)


# Marca que indica que o PDF veio do PJe (1g ou 2g do TJBA — mesmo
# template). Aparece no cabeçalho de TODA página exportada do sistema.
# Tolerante a perda de acento (alguns extractores podem entregar
# "Eletronico" sem o til).
_PJE_MARKER_RE = re.compile(
    r"PJe\s*-\s*Processo\s+Judicial\s+Eletr[ôo]nico",
    re.IGNORECASE,
)


def detect_template(pages: List[str]) -> BaseExtractor:
    """
    Inspeciona as primeiras páginas e devolve o extractor apropriado.

    PJe é detectado pela string-marca no template padrão (presente em
    todas as páginas). Se não bater, devolve o FallbackExtractor.
    """
    sample = "\n".join(pages[:3])
    if _PJE_MARKER_RE.search(sample):
        return PjeTjbaExtractor()
    return FallbackExtractor()
