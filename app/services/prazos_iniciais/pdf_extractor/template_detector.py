"""
Decide qual extractor rodar pra um conjunto de páginas.

Sistemas suportados (na ordem de tentativa de detecção):
  1. PJe — `PJe - Processo Judicial Eletrônico`
  2. PROJUDI — `PROJUDI - Processo Judicial Digital`
  3. eproc — `Tipo documento: CAPA PROCESSO` ou `Chave Processo:`
     * TJSP-eproc-híbrido (Pasta Digital eSAJ com capa CAPA PROCESSO
       sintética) — detectado quando o CNJ é `.8.26.` (TJSP) e usa
       extractor dedicado, porque o miolo separa eventos com
       `Evento N` em vez de `Documento N`.
  4. eSAJ — URL `esaj.tjxx.jus.br` (vem na barra lateral de validação)

Sem match → FallbackExtractor (texto cru, sem estruturação).
"""

from __future__ import annotations

import re
from typing import List

from app.services.prazos_iniciais.pdf_extractor.extractors.base import (
    BaseExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.eproc import (
    EprocExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.esaj import (
    EsajExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.fallback import (
    FallbackExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.pje import (
    PjeExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.projudi import (
    ProjudiExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.tjsp_eproc import (
    TjspEprocExtractor,
)


# Tolerante a perda de acento (alguns extractores podem entregar
# "Eletronico" sem o til).
_PJE_MARKER_RE = re.compile(
    r"PJe\s*-\s*Processo\s+Judicial\s+Eletr[ôo]nico",
    re.IGNORECASE,
)
_PROJUDI_MARKER_RE = re.compile(
    r"PROJUDI\s*-\s*Processo\s+Judicial\s+Digital",
    re.IGNORECASE,
)
# eproc é detectado pela "CAPA PROCESSO" ou "Chave Processo:" — esses
# rótulos são exclusivos do eproc.
_EPROC_MARKER_RE = re.compile(
    r"Tipo\s+documento:\s*CAPA\s+PROCESSO|Chave\s+Processo:",
    re.IGNORECASE,
)
# CNJ TJSP — segmento J=8 (Justiça Estadual) + tribunal TR=26 (TJSP).
# Usado pra desempatar entre eproc real e TJSP-eproc-híbrido.
_TJSP_CNJ_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.26\.\d{4}")
# eSAJ — URL aparece em texto rotacionado (barra lateral) ou em alguns
# rodapés. O texto da barra lateral é lido INVERTIDO pelo pdfplumber, então
# aceitamos `esaj.tjxx.jus.br` (normal) E `rb.suj.xxjt.jase` (invertido).
# Também serve `pastadigital` que é exclusivo da URL de validação do eSAJ.
_ESAJ_MARKER_RE = re.compile(
    r"esaj\.tj[a-z]{2,4}\.jus\.br|"
    r"rb\.suj\.[a-z]{2,4}jt\.jase|"
    r"pastadigital|latigidatsap",
    re.IGNORECASE,
)


def detect_template(pages: List[str]) -> BaseExtractor:
    """
    Inspeciona as primeiras páginas e devolve o extractor apropriado.
    Pra eproc/eSAJ a capa pode estar nas páginas iniciais; usamos as
    primeiras 5 pra cobrir variações.
    """
    sample = "\n".join(pages[:5])

    if _PJE_MARKER_RE.search(sample):
        return PjeExtractor()
    if _PROJUDI_MARKER_RE.search(sample):
        return ProjudiExtractor()
    if _EPROC_MARKER_RE.search(sample):
        # TJSP usa o mesmo marker "CAPA PROCESSO" (capa sintética
        # adicionada ao Pasta Digital eSAJ), mas o miolo é diferente:
        # eventos em vez de documentos, layout 2-colunas em partes,
        # valor da causa quebrado por largura. Roteamos pelo CNJ.
        if _TJSP_CNJ_RE.search(sample):
            return TjspEprocExtractor()
        return EprocExtractor()
    if _ESAJ_MARKER_RE.search(sample):
        return EsajExtractor()

    return FallbackExtractor()
