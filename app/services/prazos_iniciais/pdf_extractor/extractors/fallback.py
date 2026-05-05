"""
Extractor de fallback — texto cru sem estruturação.

Quando o template não é reconhecido (ex.: tribunal sem perfil próprio
implementado ainda), devolvemos o texto extraído como blob único na
integra. Capa fica vazia — o motor de classificação principal vai
preencher o que conseguir.
"""

from __future__ import annotations

import re
from typing import List, Optional

from app.services.prazos_iniciais.pdf_extractor.extractors.base import (
    BaseExtractor,
)


# CNJ no formato NNNNNNN-DD.AAAA.J.TR.OOOO
_RE_CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


class FallbackExtractor(BaseExtractor):
    name = "fallback_text"

    def extract(self, pages: List[str]):
        from app.services.prazos_iniciais.pdf_extractor import ExtractionResult

        full_text = "\n\n".join(pages).strip()
        cnj = _extract_cnj(full_text)

        return ExtractionResult(
            success=True,
            extractor_used=self.name,
            confidence="low",
            capa_json={},
            integra_json={"texto_cru": full_text},
            cnj_number=cnj,
        )


def _extract_cnj(text: str) -> Optional[str]:
    match = _RE_CNJ.search(text)
    return match.group(0) if match else None
