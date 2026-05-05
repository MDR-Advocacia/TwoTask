"""
Extractor pra PDFs exportados do PROJUDI (TJBA legado, TJPR, TJMG, ...).

Estrutura típica (página 1 = capa formal):
    TRIBUNAL DE JUSTIÇA DO ESTADO DA BAHIA
    PODER JUDICIÁRIO
    PROJUDI - Processo Judicial Digital
    Baixado do PROJUDI em: DD/MM/AAAA
    Processo nº NNNNNNN-DD.AAAA.J.TR.OOOO
    Promovente(s): Nome CPF/CNPJ Identidade
        NOME  CPF/CNPJ
        Endereço Advogados
        ENDEREÇO  OAB ... (CRISTIANE NOVAIS FONSECA SAMPAIO)
    Promovido(s): Nome CPF/CNPJ Identidade
        NOME  CPF/CNPJ
        ...
    Classe: <classe>
    Assunto: <assunto>
    Prioridade: NORMAL
    Segredo de Justiça: Sim/Não
    Data da Distribuição: DD/MM/AAAA
    Valor da Causa: R$ X.XXX,XX
    Índice de Documentos
        Id            Data Assinatura  Documento                    Tipo
        193834213     17/03/2026 13:34 P.I.pdf                       Petição Inicial
        193834214     17/03/2026 13:34 PROCURACAO.pdf                Procuração
        ...

Páginas seguintes: documentos individuais. Cada um termina em
    Assinado eletronicamente por: NOME Id. NNNNNN - Pág. N
    Código de validação do documento: HASH a ser validado no sítio do PROJUDI - TJXX.

`Id. NNN - Pág. 1` no rodapé é o anchor da segmentação. O índice da
capa nos dá `id → tipo` que vai direto pra `document_kind` (com motor
de classificação podendo refinar depois).
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
_RE_CNJ_LABEL = re.compile(
    r"Processo\s+nº\s*(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})",
    re.IGNORECASE,
)
_RE_CLASSE = re.compile(r"^\s*Classe:\s*(.+?)\s*$", re.MULTILINE)
_RE_ASSUNTO = re.compile(r"^\s*Assunto:\s*(.+?)\s*$", re.MULTILINE)
_RE_DISTRIB = re.compile(r"Data\s+da\s+Distribuição:\s*(\d{2}/\d{2}/\d{4})")
_RE_VALOR = re.compile(r"Valor\s+da\s+Causa:\s*R\$\s*([\d.,]+)")
_RE_SEGREDO = re.compile(r"Segredo\s+de\s+Justiça:\s*(Sim|Não)", re.IGNORECASE)
_RE_TRIBUNAL_HEADER = re.compile(
    r"TRIBUNAL\s+DE\s+JUSTIÇA\s+DO\s+ESTADO\s+(D[OA]\s+\w+(?:\s+\w+)?)",
    re.IGNORECASE,
)


# Índice de documentos: linhas tipo
#   "193834213 17/03/2026 13:34 nome_arquivo.pdf  Tipo"
# Tipo é a ÚLTIMA palavra (ou poucas palavras) ao final.
_RE_LINHA_INDICE = re.compile(
    r"^\s*(\d{6,12})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+(.+?)\s+"
    r"([A-ZÀ-Ú][A-Za-zÀ-ú\s./()\-]+?)\s*$",
    re.MULTILINE,
)


# ─── Partes ────────────────────────────────────────────────────────
# Cada parte aparece em bloco "Promovente(s)" ou "Promovido(s)".
# CPF: 000.000.000-00; CNPJ: 00.000.000/0000-00
_RE_DOC_PARTE = re.compile(
    r"(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})"
)
# Advogado no PROJUDI: "OAB 12345 N XX - NOME COMPLETO"
_RE_ADVOGADO = re.compile(
    r"OAB\s+\d+(?:\s+[A-Z])?\s+[A-Z]{2}\s*[-–]\s*([A-ZÀ-Ú][A-ZÀ-Ú\s\-']+)",
    re.IGNORECASE,
)


# ─── Timeline ──────────────────────────────────────────────────────
# PROJUDI numera as páginas no escopo do processo inteiro (não por
# documento), então "Pág. 1" só aparece no PRIMEIRO doc. O anchor real
# é o próprio `Id. NNN` no rodapé — cada página carimba o Id do doc
# que a contém. Mudanças de Id sinalizam novo doc.
_RE_DOC_ID_RODAPE = re.compile(
    r"Id\.\s*(\d+)\s*-\s*P[áa]g\.\s*\d+",
    re.IGNORECASE,
)
_RE_ASSINATURA = re.compile(
    r"Assinado\s+eletronicamente\s+por:\s*(.+?)\s+Id\.",
    re.IGNORECASE,
)


class ProjudiExtractor(BaseExtractor):
    name = "projudi_v1"

    def extract(self, pages: List[str]):
        from app.services.prazos_iniciais.pdf_extractor import ExtractionResult

        full_text = "\n".join(pages)

        cnj = _extract_cnj(full_text)
        tribunal = tribunal_from_cnj(cnj) if cnj else None
        # Fallback: header "TRIBUNAL DE JUSTIÇA DO ESTADO DA BAHIA" se o
        # CNJ não bateu no mapa.
        if not tribunal and pages:
            tm = _RE_TRIBUNAL_HEADER.search(pages[0])
            if tm:
                tribunal = _normalize_tribunal_header(tm.group(1))

        capa_text = pages[0] if pages else ""
        # Mapa id -> tipo extraído do "Índice de Documentos"
        indice = _extract_indice_documentos(capa_text)
        capa = _extract_capa(capa_text, tribunal=tribunal)

        timeline = _extract_timeline(pages, indice=indice)

        capa_filled = sum(
            1
            for v in (
                capa.get("tribunal"),
                capa.get("classe"),
                capa.get("data_distribuicao"),
                capa.get("valor_causa"),
                capa.get("polo_ativo"),
                capa.get("polo_passivo"),
            )
            if v
        )
        if cnj and capa_filled >= 4 and timeline:
            confidence = "high"
        elif cnj and (capa_filled >= 2 or timeline):
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


def _extract_cnj(text: str) -> Optional[str]:
    m = _RE_CNJ_LABEL.search(text)
    if m:
        return m.group(1)
    m = _RE_CNJ.search(text)
    return m.group(1) if m else None


def _parse_data_brasileira(s: str) -> Optional[date]:
    try:
        d, m, y = s.strip().split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _parse_valor_brasileiro(s: str) -> Optional[float]:
    if not s:
        return None
    cleaned = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_inline(s: str) -> str:
    return " ".join(s.split())


def _normalize_tribunal_header(estado_raw: str) -> str:
    """'DA BAHIA' → 'TJBA'; 'DO PARANÁ' → 'TJPR'; etc."""
    estado = _normalize_inline(estado_raw).upper()
    estado = estado.removeprefix("DA ").removeprefix("DO ").strip()
    sigla_map = {
        "ACRE": "TJAC", "ALAGOAS": "TJAL", "AMAPÁ": "TJAP", "AMAZONAS": "TJAM",
        "BAHIA": "TJBA", "CEARÁ": "TJCE", "DISTRITO FEDERAL": "TJDFT",
        "ESPÍRITO SANTO": "TJES", "GOIÁS": "TJGO", "MARANHÃO": "TJMA",
        "MATO GROSSO": "TJMT", "MATO GROSSO DO SUL": "TJMS",
        "MINAS GERAIS": "TJMG", "PARÁ": "TJPA", "PARAÍBA": "TJPB",
        "PARANÁ": "TJPR", "PERNAMBUCO": "TJPE", "PIAUÍ": "TJPI",
        "RIO DE JANEIRO": "TJRJ", "RIO GRANDE DO NORTE": "TJRN",
        "RIO GRANDE DO SUL": "TJRS", "RONDÔNIA": "TJRO", "RORAIMA": "TJRR",
        "SANTA CATARINA": "TJSC", "SERGIPE": "TJSE", "SÃO PAULO": "TJSP",
        "TOCANTINS": "TJTO",
    }
    return sigla_map.get(estado, "")


def _extract_capa(capa_text: str, *, tribunal: Optional[str]) -> dict:
    capa: dict = {}

    if tribunal:
        capa["tribunal"] = tribunal

    m = _RE_CLASSE.search(capa_text)
    if m:
        capa["classe"] = _normalize_inline(m.group(1))

    m = _RE_ASSUNTO.search(capa_text)
    if m:
        capa["assunto"] = _normalize_inline(m.group(1))

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

    m = _RE_SEGREDO.search(capa_text)
    if m:
        capa["segredo_justica"] = m.group(1).strip().lower() == "sim"

    polo_ativo, polo_passivo = _extract_partes(capa_text)
    if polo_ativo or polo_passivo:
        capa["polo_ativo"] = polo_ativo
        capa["polo_passivo"] = polo_passivo

    return capa


def _extract_partes(capa_text: str) -> tuple[list[dict], list[dict]]:
    """
    PROJUDI separa em blocos textuais: 'Promovente(s):' e 'Promovido(s):'.
    Cada bloco vai até o próximo cabeçalho conhecido (Promovido, Classe,
    Testemunha, Terceiro, etc.). Dentro do bloco, regex pega NOME + DOC
    + linhas de advogado (OAB ...).
    """
    polo_ativo = _parse_polo(capa_text, "Promovente(s):")
    polo_passivo = _parse_polo(capa_text, "Promovido(s):")
    return polo_ativo, polo_passivo


_BOUNDARIES = (
    "Promovente(s):", "Promovido(s):", "Testemunha(s):", "Terceiro(s):",
    "Classe:", "Assunto:", "Prioridade:", "Segredo de Justiça:",
    "Data da Distribuição:", "Valor da Causa:", "Índice de Documentos",
)


def _slice_section(text: str, header: str) -> str:
    """Retorna o trecho de `text` entre `header` e o próximo cabeçalho."""
    start = text.find(header)
    if start < 0:
        return ""
    start += len(header)
    end = len(text)
    for b in _BOUNDARIES:
        if b == header:
            continue
        idx = text.find(b, start)
        if idx >= 0 and idx < end:
            end = idx
    return text[start:end]


def _parse_polo(capa_text: str, header: str) -> list[dict]:
    bloco = _slice_section(capa_text, header)
    if not bloco.strip():
        return []

    partes: list[dict] = []

    # Cada parte ocupa ~2-4 linhas: NOME, DOC, ENDEREÇO, ADVOGADOS.
    # Dividimos pelo padrão de DOC (CPF/CNPJ).
    fragmentos = []
    last_end = 0
    for m in _RE_DOC_PARTE.finditer(bloco):
        # Captura NOME nas ~80 chars antes do match
        before = bloco[last_end:m.start()]
        after = bloco[m.end():m.end() + 600]  # 600 chars seguintes
        fragmentos.append((before, m.group(1), after))
        last_end = m.end() + 600

    papel = "Autor" if "Promovente" in header else "Reu"

    for before, doc, after in fragmentos:
        # Nome: a primeira linha "limpa" em maiúsculo ANTES do DOC
        nome = _extract_nome_antes_doc(before)
        if not nome:
            continue
        # Advogados: regex no `after`
        advogados = []
        for am in _RE_ADVOGADO.finditer(after):
            adv_nome = _normalize_inline(am.group(1)).title()
            if len(adv_nome) > 3 and adv_nome not in advogados:
                advogados.append(adv_nome)
        partes.append({
            "nome": nome.title(),
            "documento": doc,
            "papel": papel,
            "advogados": advogados,
        })

    return partes


_NOISE_PARTE = {
    "NOME", "ENDEREÇO", "ENDERECO", "ADVOGADOS", "CPF/CNPJ", "IDENTIDADE",
    "PROMOVENTE(S)", "PROMOVIDO(S)", "TESTEMUNHA(S)", "TERCEIRO(S)",
}


def _extract_nome_antes_doc(before: str) -> Optional[str]:
    """Procura um nome (linha em maiúsculo) nos últimos 5 linhas antes do DOC."""
    lines = [ln.strip() for ln in before.split("\n") if ln.strip()]
    for line in reversed(lines[-5:]):
        # Filtra cabeçalhos da tabela
        if line.upper() in _NOISE_PARTE:
            continue
        # Pega "NOME COMPLETO" — pelo menos 2 palavras maiúsculas com 3+ chars
        if re.match(r"^[A-ZÀ-Ú][A-ZÀ-Ú0-9\s./&\-']+$", line) and len(line) >= 4:
            return _normalize_inline(line)
    return None


def _extract_indice_documentos(capa_text: str) -> dict[int, str]:
    """
    Lê a tabela "Índice de Documentos" da capa do PROJUDI, retornando
    `{document_id: tipo}` (ex.: {193834213: "Petição Inicial"}).

    O motor de classificação principal pode refinar/normalizar, mas
    pré-popular `document_kind` com o tipo do PROJUDI economiza
    inferência em casos óbvios.
    """
    inicio = capa_text.find("Índice de Documentos")
    if inicio < 0:
        return {}
    bloco = capa_text[inicio:]
    indice: dict[int, str] = {}
    for m in _RE_LINHA_INDICE.finditer(bloco):
        try:
            doc_id = int(m.group(1))
        except ValueError:
            continue
        tipo = _normalize_inline(m.group(5))
        if not tipo or tipo.upper() == "TIPO":
            continue
        indice[doc_id] = tipo
    return indice


def _extract_timeline(
    pages: List[str], *, indice: dict[int, str]
) -> list[dict]:
    """
    Agrupa páginas consecutivas que carimbam o mesmo `Id. N` no rodapé.
    Cada grupo vira um documento. A capa (página 1, sem rodapé de Id)
    e páginas administrativas com Id ausente são puladas.
    """
    if not pages:
        return []

    # Pra cada página, identifica o Id do doc dela.
    page_ids: list[Optional[int]] = []
    for page in pages:
        m = _RE_DOC_ID_RODAPE.search(page)
        if m:
            try:
                page_ids.append(int(m.group(1)))
            except ValueError:
                page_ids.append(None)
        else:
            page_ids.append(None)

    # Agrupa páginas consecutivas com mesmo Id.
    groups: list[tuple[int, list[str]]] = []
    current_id: Optional[int] = None
    current_pages: list[str] = []
    for page, pid in zip(pages, page_ids):
        if pid is None:
            # Página sem rodapé conhecido — anexa ao doc atual se já
            # estamos dentro de um. Senão, ignora (capa, pré-doc).
            if current_id is not None:
                current_pages.append(page)
            continue
        if pid != current_id:
            if current_id is not None and current_pages:
                groups.append((current_id, current_pages))
            current_id = pid
            current_pages = [page]
        else:
            current_pages.append(page)
    if current_id is not None and current_pages:
        groups.append((current_id, current_pages))

    timeline: list[dict] = []
    for document_id, doc_pages in groups:
        bloco = "\n".join(doc_pages)
        cleaned = clean_document_text(bloco)
        tipo = indice.get(document_id)

        if tipo:
            label = f"{document_id} - {tipo}"
        else:
            label = _derive_label(cleaned, str(document_id))

        timeline.append({
            "document_id": document_id,
            "label": label[:160],
            "protocol_date": None,  # data vem do índice; opcional
            "timeline_date": None,
            "document_text": cleaned,
            "document_kind": tipo,  # texto livre do PROJUDI; motor refina
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
