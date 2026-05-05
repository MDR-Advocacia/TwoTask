"""
Extractor pra PDFs exportados do PJe (Processo Judicial Eletrônico).

Template é o mesmo em qualquer tribunal que use PJe (TJBA, TJRJ, TJES,
TJDFT, TRTs, TRFs do PJe…). A detecção é feita pela string-marca
`PJe - Processo Judicial Eletrônico` no template padrão.

Estrutura típica:
    Página 1 (template fixo):
        DD/MM/AAAA
        Número: NNNNNNN-DD.AAAA.J.TR.OOOO
        Classe: PROCEDIMENTO COMUM CÍVEL (7)
        Órgão julgador: 20ª VARA DE RELAÇÕES DE CONSUMO ...
        Última distribuição : DD/MM/AAAA
        Valor da causa: R$ X.XXX,XX
        Assuntos: <multilinha>
        Segredo de justiça? NÃO
        Justiça gratuita? SIM
        TJBA
        PJe - Processo Judicial Eletrônico
        Partes Advogados
        NOME (AUTOR)
        ...

    Páginas seguintes:
        Documentos individuais separados pelo marcador
        `Num. NNNNNNN - Pág. 1` no início de cada um.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import List, Optional

from app.services.prazos_iniciais.pdf_extractor.cleaner import clean_document_text
from app.services.prazos_iniciais.pdf_extractor.extractors.base import (
    BaseExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.tribunais import tribunal_from_cnj

logger = logging.getLogger(__name__)


# ─── Regex de capa ────────────────────────────────────────────────
_RE_CNJ = re.compile(r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})")
_RE_CLASSE = re.compile(r"Classe:\s*(.+?)\s*$", re.MULTILINE)
_RE_ORGAO = re.compile(r"Órgão\s+julgador(?:\s+colegiado)?:\s*(.+?)\s*$", re.MULTILINE)
_RE_DISTRIB = re.compile(r"Última\s+distribuição\s*:\s*(\d{2}/\d{2}/\d{4})", re.MULTILINE)
_RE_VALOR = re.compile(r"Valor\s+da\s+causa:\s*R\$\s*([\d.,]+)", re.MULTILINE)
_RE_SEGREDO = re.compile(r"Segredo\s+de\s+justiça\?\s*(SIM|NÃO)", re.IGNORECASE)
_RE_GRATUITA = re.compile(r"Justiça\s+gratuita\?\s*(SIM|NÃO)", re.IGNORECASE)
_RE_ASSUNTOS_BLOCO = re.compile(
    r"Assuntos:\s*(.+?)(?=Segredo\s+de\s+justiça\?)",
    re.IGNORECASE | re.DOTALL,
)


# ─── Regex de partes/advogados ─────────────────────────────────────
_PAPEIS_POLO_ATIVO = {
    "AUTOR", "AGRAVANTE", "REQUERENTE", "EXEQUENTE",
    "IMPETRANTE", "EMBARGANTE", "RECORRENTE", "APELANTE",
}
_PAPEIS_POLO_PASSIVO = {
    "REU", "RÉU", "AGRAVADO", "REQUERIDO", "EXECUTADO",
    "IMPETRADO", "EMBARGADO", "RECORRIDO", "APELADO",
}
_PAPEIS_AUX = {"INTERESSADO", "TERCEIRO", "VÍTIMA", "VITIMA", "ADVOGADO"}

_PAPEIS_TODOS = (
    _PAPEIS_POLO_ATIVO | _PAPEIS_POLO_PASSIVO | _PAPEIS_AUX
)

_RE_PAPEL_INLINE = re.compile(
    r"\(\s*(" + "|".join(re.escape(p) for p in _PAPEIS_TODOS) + r")\s*\)",
    re.IGNORECASE,
)


# ─── Regex pra timeline (separadores) ──────────────────────────────
_RE_DOC_INICIO = re.compile(
    r"Num\.\s*(\d+)\s*-\s*P[áa]g\.\s*1\b",
    re.IGNORECASE,
)
_RE_ASSINATURA_BLOCO = re.compile(
    r"Assinado\s+(?:eletronicamente|digitalmente)\s+por:\s*(.+?)\s*-\s*"
    r"(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}",
    re.IGNORECASE,
)


class PjeExtractor(BaseExtractor):
    name = "pje_v1"

    def extract(self, pages: List[str]):
        from app.services.prazos_iniciais.pdf_extractor import ExtractionResult

        full_text = "\n".join(pages)

        cnj = _extract_cnj(full_text)
        tribunal = tribunal_from_cnj(cnj) if cnj else None

        capa_text = pages[0] if pages else ""
        capa = _extract_capa(capa_text, tribunal=tribunal)

        timeline = _extract_timeline(full_text)

        capa_filled = sum(
            1
            for v in (
                capa.get("tribunal"),
                capa.get("classe"),
                capa.get("vara"),
                capa.get("data_distribuicao"),
                capa.get("valor_causa"),
                capa.get("polo_ativo"),
                capa.get("polo_passivo"),
            )
            if v
        )
        if cnj and capa_filled >= 5 and timeline:
            confidence = "high"
        elif cnj and (capa_filled >= 3 or timeline):
            confidence = "partial"
        else:
            confidence = "low"

        return ExtractionResult(
            success=True,
            extractor_used=self.name,
            confidence=confidence,
            capa_json=capa,
            integra_json={"timeline": timeline},
            cnj_number=cnj,
        )


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────


def _extract_cnj(text: str) -> Optional[str]:
    m = _RE_CNJ.search(text)
    return m.group(1) if m else None


def _parse_data_brasileira(s: str) -> Optional[date]:
    """DD/MM/AAAA → date."""
    try:
        d, m, y = s.strip().split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _parse_valor_brasileiro(s: str) -> Optional[float]:
    """'132.163,36' → 132163.36"""
    if not s:
        return None
    cleaned = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_capa(capa_text: str, *, tribunal: Optional[str]) -> dict:
    capa: dict = {}

    if tribunal:
        capa["tribunal"] = tribunal

    m = _RE_CLASSE.search(capa_text)
    if m:
        capa["classe"] = _normalize_inline(m.group(1))

    m = _RE_ORGAO.search(capa_text)
    if m:
        capa["vara"] = _normalize_inline(m.group(1))

    m = _RE_DISTRIB.search(capa_text)
    if m:
        d = _parse_data_brasileira(m.group(1))
        if d:
            capa["data_distribuicao"] = d.isoformat()

    m = _RE_VALOR.search(capa_text)
    if m:
        v = _parse_valor_brasileiro(m.group(1))
        if v is not None:
            capa["valor_causa"] = v

    m = _RE_ASSUNTOS_BLOCO.search(capa_text)
    if m:
        bloco = m.group(1).strip()
        capa["assunto"] = "\n".join(
            ln.strip() for ln in bloco.splitlines() if ln.strip()
        )

    m = _RE_SEGREDO.search(capa_text)
    if m:
        capa["segredo_justica"] = m.group(1).upper() == "SIM"

    m = _RE_GRATUITA.search(capa_text)
    if m:
        capa["justica_gratuita"] = m.group(1).upper() == "SIM"

    polo_ativo, polo_passivo = _extract_partes(capa_text)
    if polo_ativo or polo_passivo:
        capa["polo_ativo"] = polo_ativo
        capa["polo_passivo"] = polo_passivo

    return capa


def _normalize_inline(s: str) -> str:
    return " ".join(s.split())


def _extract_partes(capa_text: str) -> tuple[list[dict], list[dict]]:
    polo_ativo: list[dict] = []
    polo_passivo: list[dict] = []
    last_parte: Optional[dict] = None
    seen_keys: set[tuple[str, str]] = set()

    _NOISE = {
        "PARTES", "ADVOGADOS", "DOCUMENTOS", "TJBA",
        "PJE - PROCESSO JUDICIAL ELETRÔNICO",
    }

    lines = [ln.rstrip() for ln in capa_text.split("\n")]

    for i, line in enumerate(lines):
        m = _RE_PAPEL_INLINE.search(line)
        if not m:
            continue

        papel_raw = m.group(1).upper().replace("É", "E")
        before_paren = line[:m.start()].strip()

        if before_paren:
            nome_raw = before_paren
        else:
            nome_raw = ""
            for j in range(i - 1, max(-1, i - 5), -1):
                candidato = lines[j].strip()
                if not candidato:
                    continue
                if _RE_PAPEL_INLINE.search(candidato):
                    continue
                nome_raw = candidato
                break

        nome = _normalize_inline(nome_raw)
        if not nome or len(nome) < 2 or nome.upper() in _NOISE:
            continue

        nome = nome.title()

        if papel_raw == "ADVOGADO":
            if last_parte is not None:
                if nome not in last_parte["advogados"]:
                    last_parte["advogados"].append(nome)
            continue

        if papel_raw in {"RÉU", "REU"}:
            papel_norm = "Reu"
            destino = polo_passivo
        elif papel_raw in _PAPEIS_POLO_ATIVO:
            papel_norm = papel_raw.title()
            destino = polo_ativo
        elif papel_raw in _PAPEIS_POLO_PASSIVO:
            papel_norm = papel_raw.title()
            destino = polo_passivo
        else:
            papel_norm = papel_raw.title()
            destino = polo_passivo

        key = (nome.upper(), papel_norm.upper())
        if key in seen_keys:
            last_parte = next(
                (p for p in destino if p["nome"].upper() == nome.upper()),
                None,
            )
            continue
        seen_keys.add(key)

        parte = {
            "nome": nome,
            "documento": None,
            "papel": papel_norm,
            "advogados": [],
        }
        destino.append(parte)
        last_parte = parte

    return polo_ativo, polo_passivo


def _extract_timeline(full_text: str) -> list[dict]:
    matches = list(_RE_DOC_INICIO.finditer(full_text))
    if not matches:
        return []

    timeline: list[dict] = []

    for i, m in enumerate(matches):
        document_id = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        bloco = full_text[start:end]

        sig_match = _RE_ASSINATURA_BLOCO.search(bloco)
        protocol_date_iso: Optional[str] = None
        if sig_match:
            d = _parse_data_brasileira(sig_match.group(2))
            if d:
                protocol_date_iso = d.isoformat()

        cleaned = clean_document_text(bloco)

        label = _derive_label(cleaned, document_id)

        timeline.append({
            "document_id": int(document_id),
            "label": label,
            "protocol_date": protocol_date_iso,
            "timeline_date": protocol_date_iso,
            "document_text": cleaned,
            "document_kind": None,  # motor de classificação resolve
        })

    return timeline


def _derive_label(text: str, document_id: str) -> str:
    if not text:
        return f"Documento {document_id}"
    for line in text.splitlines():
        s = line.strip()
        if len(s) >= 4 and not s.isdigit():
            return f"{document_id} - {s[:120]}"
    return f"Documento {document_id}"
