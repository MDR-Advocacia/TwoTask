"""
Extractor pra PDFs exportados do eproc (TJRS, TJSC parcial, TRFs).

Estrutura típica:
    Página 1 — "carimbo" minimal:
        Tipo documento: CAPA PROCESSO
        Evento: abertura
        PROCESSO
        Nº NNNNNNNDDAAAAJTROOOO

    Página 2 — capa formal:
        Nº do processo NNNNNNN-DD.AAAA.J.TR.OOOO
        Classe da ação: PROCEDIMENTO COMUM CÍVEL
        Competência ...
        Data de autuação: DD/MM/AAAA HH:MM:SS
        Situação ...
        Órgão Julgador: Juízo da Xª Vara ...
        Juiz(a): NOME
        Assuntos
            Código Descrição Principal
            ...
        Partes e Representantes
            AUTOR                      RÉU
            NOME (CPF/CNPJ) - Pessoa Física/Jurídica   NOME (CPF/CNPJ) - Pessoa Jurídica
            (Procurador) NOME OAB-UF   Procurador(es): NOME OAB-UF
        Informações Adicionais
            Chave Processo: ...   Valor da Causa: R$ X.XXX,XX  ...
            Justiça Gratuita: Deferida   ...

    Páginas seguintes — documentos individuais:
        PÁGINA DE SEPARAÇÃO
        (Gerada automaticamente pelo sistema.)
        Documento N
        Tipo documento: <X>
        Evento: <Y>
        Data: DD/MM/AAAA HH:MM:SS
        Usuário: SIGLA - NOME
        Processo: NNN
        Sequência Evento: N
        ... <conteúdo do doc> ...
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
_RE_CLASSE = re.compile(r"^\s*Classe\s+da\s+ação:\s*(.+?)\s*$", re.MULTILINE)
_RE_ORGAO = re.compile(r"^\s*Órgão\s+Julgador:\s*(.+?)\s*$", re.MULTILINE)
_RE_AUTUACAO = re.compile(r"Data\s+de\s+autuação:\s*(\d{2}/\d{2}/\d{4})")
_RE_VALOR = re.compile(r"Valor\s+da\s+Causa:\s*R\$\s*([\d.,]+)")
_RE_GRATUITA = re.compile(r"Justiça\s+Gratuita:\s*(Deferida|Indeferida|Não\s+há\s+pedido)", re.IGNORECASE)
_RE_SIGILO = re.compile(r"Nível\s+de\s+Sigilo[^:]*:\s*(.+?)(?=\s{2,}|\n|$)", re.IGNORECASE)
_RE_ASSUNTOS_BLOCO = re.compile(
    r"Assuntos\s*\n\s*Código\s+Descrição\s+Principal\s*\n(.+?)(?=Partes\s+e\s+Representantes)",
    re.DOTALL,
)

# Linha de assunto: "06040102 Empréstimo consignado, Bancários, ... DIREITO DO CONSUMIDOR Sim/Não"
_RE_LINHA_ASSUNTO = re.compile(
    r"^\s*(\d{4,8})\s+(.+?)\s+(Sim|Não)\s*$",
    re.MULTILINE,
)

# Partes: "NOME (CPF/CNPJ) - Pessoa Física/Jurídica"
# CPF: 000.000.000-00 / CNPJ: 00.000.000/0000-00
_RE_PARTE_LINHA = re.compile(
    r"([A-ZÀ-Ú][A-ZÀ-Ú0-9\s./&\-']+?)\s*"
    r"\((\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\)\s*-\s*"
    r"Pessoa\s+(Física|Jurídica)",
)
# Procurador: "NOME RS099005" / "NOME RN005553" / "NOME SP123456" — sigla 2 letras + 6 dígitos
_RE_PROCURADOR = re.compile(
    r"([A-ZÀ-Ú][A-ZÀ-Ú\s\-']+?)\s+([A-Z]{2}\d{4,7})\b",
)


# ─── Marcador de timeline ──────────────────────────────────────────
# Documento N inicia na linha "Documento N" precedida por
# "PÁGINA DE SEPARAÇÃO". Pode ter ou não a "PÁGINA DE SEPARAÇÃO" --
# usamos o "Documento N" como anchor primário.
_RE_DOC_INICIO = re.compile(
    r"^\s*Documento\s+(\d+)\s*$",
    re.MULTILINE,
)
_RE_DOC_METADATA = re.compile(
    r"Tipo\s+documento:\s*(.+?)\s*\n"
    r"Evento:\s*(.+?)\s*\n"
    r"Data:\s*(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}:\d{2}\s*\n"
    r"Usuário:\s*(.+?)\s*\n",
    re.IGNORECASE,
)


class EprocExtractor(BaseExtractor):
    name = "eproc_v1"

    def extract(self, pages: List[str]):
        from app.services.prazos_iniciais.pdf_extractor import ExtractionResult

        full_text = "\n".join(pages)

        cnj = _extract_cnj(full_text)
        tribunal = tribunal_from_cnj(cnj) if cnj else None

        # Capa quase sempre na página 2 (página 1 = "carimbo" mínimo
        # com só CNJ). Concatenamos as 2 primeiras pra robustez.
        capa_text = "\n".join(pages[:3]) if pages else ""
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


def _extract_cnj(text: str) -> Optional[str]:
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

    m = _RE_AUTUACAO.search(capa_text)
    if m:
        d = _parse_data_brasileira(m.group(1))
        if d:
            capa["data_distribuicao"] = d.isoformat()

    m = _RE_VALOR.search(capa_text)
    if m:
        v = _parse_valor_brasileiro(m.group(1))
        if v is not None:
            capa["valor_causa"] = v

    m = _RE_GRATUITA.search(capa_text)
    if m:
        capa["justica_gratuita"] = m.group(1).strip().lower() == "deferida"

    m = _RE_SIGILO.search(capa_text)
    if m:
        # "Sem Sigilo (Nível 0)" → False; qualquer outra coisa → True
        capa["segredo_justica"] = "sem sigilo" not in m.group(1).strip().lower()

    # Assuntos: bloco tabelar.
    m = _RE_ASSUNTOS_BLOCO.search(capa_text)
    if m:
        bloco = m.group(1)
        assuntos = []
        for am in _RE_LINHA_ASSUNTO.finditer(bloco):
            codigo, descricao, _principal = am.groups()
            assuntos.append(f"{descricao.strip()} ({codigo})")
        if assuntos:
            capa["assunto"] = "\n".join(assuntos)

    polo_ativo, polo_passivo = _extract_partes(capa_text)
    if polo_ativo or polo_passivo:
        capa["polo_ativo"] = polo_ativo
        capa["polo_passivo"] = polo_passivo

    return capa


def _extract_partes(capa_text: str) -> tuple[list[dict], list[dict]]:
    """
    eproc usa tabela 2-colunas "AUTOR | RÉU". O `extract_text` do
    pdfplumber junta as colunas, então cada linha pode ter:
      - 2 partes (uma de cada polo) na mesma linha
      - 1 parte sozinha (quando coluna oposta tá vazia)

    Quando o limite de largura quebra um CNPJ entre linhas (ex:
    "(33.923.798/0001-\n00)"), juntamos essas linhas antes do regex.

    Estratégia: detecta a seção "Partes e Representantes" e itera por
    matches `(NOME) (CPF/CNPJ) - Pessoa X/J`. Na 1ª ocorrência por linha
    é o polo ativo; na 2ª, polo passivo. Procuradores anexam à última
    parte vista do MESMO polo.
    """
    polo_ativo: list[dict] = []
    polo_passivo: list[dict] = []

    # Recorta a seção de partes pra evitar false-positives em outros
    # blocos (Informações Adicionais tem outros números).
    inicio = capa_text.find("Partes e Representantes")
    fim = capa_text.find("Informações Adicionais")
    if inicio < 0:
        return polo_ativo, polo_passivo
    if fim < 0:
        fim = len(capa_text)
    bloco = capa_text[inicio:fim]

    # Junta CNPJ/CPF quebrado entre linhas (largura da coluna estoura
    # justamente no doc): "(NN.NNN.NNN/NNNN-\nNN) - Pessoa X" → uma
    # linha só. Idem pra CPFs partidos.
    bloco = re.sub(
        r"(\(\d[\d./\-]*?)\n([\d./\-]+?\))",
        r"\1\2",
        bloco,
    )

    last_ativo: Optional[dict] = None
    last_passivo: Optional[dict] = None
    seen_keys: set[tuple[str, str]] = set()

    for line in bloco.splitlines():
        partes_na_linha = list(_RE_PARTE_LINHA.finditer(line))
        for idx, m in enumerate(partes_na_linha):
            nome_raw, doc, tipo_pessoa = m.groups()
            nome = _normalize_inline(nome_raw).title()
            if len(nome) < 2:
                continue
            # 1ª ocorrência = ativo, 2ª = passivo (tabela 2 colunas)
            destino = polo_ativo if idx == 0 else polo_passivo
            papel = "Autor" if destino is polo_ativo else "Reu"
            key = (nome.upper(), papel)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            parte = {
                "nome": nome,
                "documento": doc,
                "papel": papel,
                "advogados": [],
            }
            destino.append(parte)
            if destino is polo_ativo:
                last_ativo = parte
            else:
                last_passivo = parte

        # Procuradores podem aparecer em linhas sem parte. Detecta e
        # anexa à última parte do polo correspondente. Se a linha tem
        # 2 procuradores (esquerda + direita), distribui pelos dois.
        if not partes_na_linha:
            procuradores = list(_RE_PROCURADOR.finditer(line))
            for j, pm in enumerate(procuradores):
                nome_proc = _normalize_inline(pm.group(1)).title()
                if len(nome_proc) < 3:
                    continue
                destino_parte = (
                    last_ativo if j == 0 and last_ativo
                    else last_passivo if last_passivo
                    else last_ativo
                )
                if destino_parte is not None:
                    if nome_proc not in destino_parte["advogados"]:
                        destino_parte["advogados"].append(nome_proc)

    return polo_ativo, polo_passivo


def _extract_timeline(full_text: str) -> list[dict]:
    """
    Segmenta por `Documento N` (linha isolada). Para cada bloco, tenta
    extrair Tipo/Evento/Data/Usuário das próximas linhas.
    """
    matches = list(_RE_DOC_INICIO.finditer(full_text))
    if not matches:
        return []

    timeline: list[dict] = []

    for i, m in enumerate(matches):
        document_id = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        bloco = full_text[start:end]

        # Metadata oficial do eproc — primeiras linhas do bloco
        meta_match = _RE_DOC_METADATA.search(bloco[:500])
        tipo_doc: Optional[str] = None
        protocol_date_iso: Optional[str] = None
        if meta_match:
            tipo_doc = _normalize_inline(meta_match.group(1))
            d = _parse_data_brasileira(meta_match.group(3))
            if d:
                protocol_date_iso = d.isoformat()

        cleaned = clean_document_text(bloco)

        label = (
            f"{document_id} - {tipo_doc}"
            if tipo_doc
            else _derive_label(cleaned, document_id)
        )

        timeline.append({
            "document_id": int(document_id),
            "label": label[:160],
            "protocol_date": protocol_date_iso,
            "timeline_date": protocol_date_iso,
            "document_text": cleaned,
            "document_kind": None,  # motor decide; eproc 'Tipo documento'
                                    # vira hint via label
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
