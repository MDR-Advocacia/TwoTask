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

from app.services.prazos_iniciais.pdf_extractor.cleaner import clean_document_text
from app.services.prazos_iniciais.pdf_extractor.extractors.base import (
    BaseExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.tribunais import tribunal_from_cnj

logger = logging.getLogger(__name__)


# CNJ no formato com máscara
_RE_CNJ = re.compile(r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})")

# ─── Capa rica (parseada da petição inicial) ─────────────────────────
# Endereçamento típico do eSAJ TJSP:
#   "EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA ___ª
#    VARA DA FAZENDA PÚBLICA NA COMARCA DO ESTADO DE SÃO PAULO."
#   "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA ___ª VARA CÍVEL DO FORO
#    CENTRAL DA COMARCA DE SÃO PAULO - SP."
# O `___` é placeholder do número da vara (preenchido na distribuição).
# Pega tudo entre `VARA` e o ponto final ou primeiro nome próprio nominal.
_RE_VARA = re.compile(
    r"JUIZ[A]?\s*(?:\([A]\))?\s+(?:DE\s+DIREITO\s+)?DA[\s\S]{0,80}?"
    # `___ª` (placeholder) ou número, podendo ter \n entre `ª` e `VARA`
    r"((?:\d+|_+)\s*[ªº]?\s*\n?\s*VARA\s+[A-ZÀ-Ú\s/\.\-]+?(?:COMARCA\s+(?:DO\s+ESTADO\s+)?DE\s+[A-ZÀ-Ú\s\-]+?)?)\s*\.",
    re.IGNORECASE,
)

# Classe — frases típicas no início da peça. Aceitamos qualquer "a
# presente <CLASSE>" (com ou sem "propor"/"propõe"). Stop no primeiro
# "em face de" ou após o trecho longo de classe (~300 chars).
# Char set inclui parênteses pra captar trechos tipo "(IPREM-SP)" no
# nome do réu, que pode aparecer entre classe e "em face de".
_RE_CLASSE_TJSP = re.compile(
    r"a\s+presente\s*\n+"
    r"([A-ZÀ-Ú][A-ZÀ-Ú\s/\-()]{10,400}?)"
    r"(?:\n\s*em\s+face\s+de|\n\s*EM\s+FACE\s+DE)",
    re.IGNORECASE,
)

# Valor da causa — formas comuns:
#   "Dá-se à causa o valor de R$ X.XXX,XX"
#   "Atribui-se à causa o valor de R$ X.XXX,XX"
#   "Valor da causa: R$ X.XXX,XX"
#   "ao valor da causa, qual seja, R$ X.XXX,XX"
#   "atribui o valor de R$ X.XXX,XX"
# Estratégia: junta vários gatilhos comuns e captura o R$ logo após.
_RE_VALOR_CAUSA = re.compile(
    r"(?:[Dd]á[\s\-]se\s+à\s+causa|"
    r"[Aa]tribui[\s\-]?se?\s+à?\s*causa\s+o\s+valor|"
    r"[Vv]alor\s+da\s+[Cc]ausa\s*[:\-]?|"
    r"[Vv]alor\s+atribu[íi]do\s+à\s+causa)"
    r"[\s\S]{0,150}?R\$\s*([\d.]+,\d{2})",
)

# Data de protocolo — vem do carimbo invertido (antes de remover pelo cleaner).
# Padrão observado: "AAAA/MM/DD\nme\nodalocotorp" — TODOS os componentes
# estão invertidos individualmente, mas separados por "/". Ex.:
# "5202/01/92\nme\nodalocotorp" = data real 29/10/2025 (cada componente
# precisa ser revertido).
_RE_DATA_PROTOCOLO = re.compile(
    r"(\d{4})/(\d{2})/(\d{2})\s*\n\s*me\s*\n\s*odalocotorp",
    re.IGNORECASE,
)

# Polo ativo: nome em CAIXA ALTA logo após o endereçamento, seguido de
# ", brasileir[ao]" / ", aposentad[ao]" / ", solteir[ao]" / etc. — a
# qualificação civil é o marcador mais estável (sempre vem depois do
# nome do autor na inicial). Aceita acentos e até 5 palavras no nome.
_RE_POLO_ATIVO = re.compile(
    r"\.\s*\n+"  # ponto final do endereçamento + quebra(s)
    r"([A-ZÀ-Ú][A-ZÀ-Ú\s\-\.']{4,80}?)"  # nome em CAIXA ALTA (2-5 palavras)
    r"\s*\n?\s*,\s*"  # vírgula
    r"(?:brasileir[ao]|aposentad[ao]|solteir[ao]|casad[ao]|"
    r"divorciad[ao]|viúv[ao]|portugues[ao]|estrangeir[ao])",
    re.IGNORECASE,
)

# Polo passivo: lista de CNPJs após "em face de". Captura CNJ-fashion
# 14 dígitos com pontuação. Como o eSAJ Pasta Digital tem ordem de
# texto bagunçada (nomes intercalados), pegamos os CNPJs e o BLOCO
# antes do primeiro "pelos motivos de fato"/"com fundamentos nas razões"
# que delimita o final da seção de qualificação dos réus.
_RE_BLOCO_EM_FACE_DE = re.compile(
    r"em\s+face\s+de[\s\S]{0,5000}?"
    r"(?:pelos\s+motivos\s+de\s+fato|com\s+fundamentos\s+nas\s+razões|"
    r"PRELIMINARMENTE|DOS\s+FATOS|D[OE]S?\s+DIREITO)",
    re.IGNORECASE,
)

_RE_CNPJ = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")

# Nomes de PJ em CAIXA ALTA por LINHA — heurística: linha inteira em
# CAIXA ALTA contendo termos jurídicos típicos. Por linha (não cross-line)
# porque o eSAJ Pasta Digital separa cada nome de réu em linha própria
# (mesmo quando o layout 2-colunas embaralha a ordem).
# Termos âncora: S/A, S.A, LTDA, S.A. nos sufixos, ou palavras-chave de
# entidades públicas (INSTITUTO, FUNDAÇÃO, etc) no nome.
_RE_NOME_PJ_LINHA = re.compile(
    r"^\s*("
    # Caso 1: nome termina com sufixo societário típico
    r"[A-ZÀ-Ú][A-ZÀ-Ú0-9\s\-\.&]{3,55}?\s*(?:S/A|S\.A|S\.A\.|LTDA|EIRELI|"
    r"PARTICIPAÇÕES|PARTICIPACOES|SEGUROS|"
    r"FINANCEIRA|FUNDO|SERVIÇOS|SERVICOS)\.?"
    r"|"
    # Caso 2: nome começa com palavra-chave de entidade pública
    r"(?:INSTITUTO|FUNDAÇÃO|FUNDACAO|UNIÃO|UNIAO|ESTADO|MUNICÍPIO|MUNICIPIO|"
    r"COMPANHIA|BANCO\s+[A-ZÀ-Ú])\s+[A-ZÀ-Ú][A-ZÀ-Ú\s\-\.\(\)]{3,60}?"
    r")\s*$",
    re.MULTILINE,
)

# Variante INLINE: nome PJ aparece dentro de "em face de NOME, pessoa
# jurídica..." (PDF2 estilo — sem quebra de linha entre "em face de" e
# o nome). Stop em vírgula ou termo descritivo.
_RE_NOME_PJ_INLINE = re.compile(
    r"em\s+face\s+de\s+("
    r"[A-ZÀ-Ú][A-ZÀ-Ú0-9\s\-\.&]{3,80}?(?:S/A|S\.A|S\.A\.|LTDA|EIRELI)\.?"
    r")(?:\s*,|\s+pessoa\s+jur)",
    re.IGNORECASE,
)


class EsajExtractor(BaseExtractor):
    name = "esaj_v1"

    def extract(self, pages: List[str]):
        from app.services.prazos_iniciais.pdf_extractor import ExtractionResult

        full_text_raw = "\n".join(pages)
        cnj = _extract_cnj(full_text_raw)
        tribunal = tribunal_from_cnj(cnj) if cnj else None

        # Captura dados da capa ANTES de limpar — alguns deles dependem
        # do carimbo invertido (data de protocolo).
        data_protocolo = _extract_data_protocolo(full_text_raw)
        vara = _extract_vara(full_text_raw)
        classe = _extract_classe(full_text_raw)
        valor_causa = _extract_valor_causa(full_text_raw)
        polo_ativo = _extract_polo_ativo(full_text_raw)
        polo_passivo = _extract_polo_passivo(full_text_raw)

        # AGORA limpa o texto bruto antes de truncar — o cleaner remove
        # ~30-40% de ruído (carimbos invertidos, URLs, headers repetidos,
        # marcadores de página). Texto limpo cabe mais conteúdo no mesmo
        # budget de chars.
        chars_antes = len(full_text_raw)
        full_text = clean_document_text(full_text_raw)
        chars_depois = len(full_text)
        logger.info(
            "EsajExtractor: cleaner reduziu %d → %d chars (%.1f%% removido)",
            chars_antes, chars_depois,
            100 * (chars_antes - chars_depois) / max(chars_antes, 1),
        )

        # Monta capa com o que conseguiu mecanicamente
        capa: dict = {}
        if tribunal:
            capa["tribunal"] = tribunal
        if classe:
            capa["classe"] = classe
        if vara:
            capa["vara"] = vara
        if valor_causa:
            capa["valor_causa"] = valor_causa
        if data_protocolo:
            capa["data_protocolo"] = data_protocolo
        if polo_ativo:
            capa["polo_ativo"] = polo_ativo
        if polo_passivo:
            capa["polo_passivo"] = polo_passivo

        # Texto cru limpo. Cap aumentado de 200k pra 300k porque o texto
        # já vem mais denso depois da limpeza.
        MAX_INTEGRA_CHARS = 300_000
        texto = full_text[:MAX_INTEGRA_CHARS] if len(full_text) > MAX_INTEGRA_CHARS else full_text

        # Confidence:
        #   - "high" se tem CNJ + (classe OU vara) + valor_causa
        #   - "partial" se tem CNJ + algum dado da capa
        #   - "low" se só tem CNJ ou nada
        confidence = "low"
        if cnj:
            confidence = "partial"
            if (classe or vara) and valor_causa:
                confidence = "high"

        return ExtractionResult(
            success=True,
            extractor_used=self.name,
            confidence=confidence,
            capa_json=capa,
            integra_json={"texto_cru": texto},
            cnj_number=cnj,
        )


def _extract_vara(text: str) -> Optional[str]:
    """Extrai a vara/foro do endereçamento da petição inicial."""
    match = _RE_VARA.search(text)
    if not match:
        return None
    vara = match.group(1).strip()
    # Limpa quebras de linha e espaços extras
    vara = " ".join(vara.split())
    # Trunca em ~120 chars (vara raramente passa disso)
    return vara[:120] if len(vara) > 120 else vara


def _extract_classe(text: str) -> Optional[str]:
    """Extrai a classe da ação do título da petição inicial."""
    match = _RE_CLASSE_TJSP.search(text)
    if not match:
        return None
    classe = match.group(1).strip()
    classe = " ".join(classe.split())
    return classe[:200] if len(classe) > 200 else classe


def _extract_valor_causa(text: str) -> Optional[str]:
    """Extrai o valor da causa em formato 'R$ X.XXX,XX'."""
    match = _RE_VALOR_CAUSA.search(text)
    if not match:
        return None
    return f"R$ {match.group(1)}"


def _extract_polo_ativo(text: str) -> list[dict]:
    """Extrai o autor (polo ativo) como list[dict] no formato dos extractors PI.

    Formato compatível com PJe/eproc/PROJUDI/TJSP-eproc:
        [{"nome": "...", "documento": None, "papel": "Autor", "advogados": []}]

    Devolve lista vazia se não conseguir extrair.
    """
    match = _RE_POLO_ATIVO.search(text)
    if not match:
        return []
    nome = " ".join(match.group(1).split())
    if len(nome) < 5 or len(nome.split()) < 2:
        return []
    return [{
        "nome": nome[:120].title(),
        "documento": None,
        "papel": "Autor",
        "advogados": [],
    }]


def _extract_polo_passivo(text: str) -> list[dict]:
    """Extrai os réus (polo passivo) como list[dict] no formato dos extractors PI.

    Formato compatível:
        [{"nome": "...", "documento": "CNPJ", "papel": "Reu", "advogados": []}, ...]

    IMPORTANTE: o pdfplumber lê o eSAJ Pasta Digital com layout 2-colunas
    em ordem ERRADA — nomes e CNPJs vêm intercalados em ordem fora do
    Z-pattern visual. Tentamos parear nome+CNPJ pela ordem do texto e o
    resultado fica enganoso (CNPJ de A pareado com nome de B).

    Estratégia: entrega entradas SEPARADAS — uma por nome detectado
    (sem documento) + uma por CNPJ órfão (sem nome). A IA pareia depois
    com base em conhecimento prévio (Master = 33.923.798/0001-XX, BB =
    00.000.000/0001-91, etc.) e na lista de vinculadas Master injetada
    no prompt.
    """
    em_face = re.search(r"em\s+face\s+de", text, re.IGNORECASE)
    if not em_face:
        return []
    # Janela: 800 chars antes (lookback p/ nomes pré-"em face de"
    # do layout 2-colunas, ex.: IPREM no PDF1) + 5000 chars depois.
    start = max(0, em_face.start() - 800)
    end = em_face.end() + 5000
    janela = text[start:end]
    # Trunca no marcador de fim de qualificação dos réus, mas SOMENTE
    # após o "em face de" (não cair no "DE DIREITO" do endereçamento).
    pos_em_face_na_janela = em_face.start() - start
    fim_match = re.search(
        r"pelos\s+motivos\s+de\s+fato|com\s+fundamentos\s+nas\s+razões|"
        r"\bPRELIMINARMENTE\b|\bDOS\s+FATOS\b|\bDO\s+DIREITO\b|"
        r"\bDA\s+TEMPESTIVIDADE\b|\bI\s*[\-\.]\s*DOS\s+FATOS",
        janela[pos_em_face_na_janela:],
        re.IGNORECASE,
    )
    if fim_match:
        janela = janela[:pos_em_face_na_janela + fim_match.end()]

    cnpjs_raw = _RE_CNPJ.findall(janela)
    cnpjs: list[str] = []
    seen_c = set()
    for c in cnpjs_raw:
        if c not in seen_c:
            seen_c.add(c); cnpjs.append(c)

    nomes_raw = (
        list(_RE_NOME_PJ_LINHA.findall(janela))
        + list(_RE_NOME_PJ_INLINE.findall(janela))
    )
    nomes: list[str] = []
    seen_n = set()
    for n in nomes_raw:
        clean = " ".join(n.split())
        if len(clean) < 5 or clean in seen_n:
            continue
        if " C/C " in clean or "AÇÃO " in clean[:10] or "PEDIDO DE " in clean:
            continue
        seen_n.add(clean); nomes.append(clean)

    if not cnpjs and not nomes:
        return []

    partes: list[dict] = []
    # Caso 1: número de nomes == número de CNPJs → pareia direto pela
    # ordem (eSAJ INLINE "em face de NOME, CNPJ" — PDF2 funciona bem).
    if len(nomes) == len(cnpjs) and len(nomes) > 0:
        for nm, cn in zip(nomes, cnpjs):
            partes.append({
                "nome": nm.title(),
                "documento": cn,
                "papel": "Reu",
                "advogados": [],
                "pareamento_mecanico": "ordem_provavel",
            })
        return partes

    # Caso 2: contagens diferentes → ordem incerta (layout 2-colunas
    # bagunçou). Entrega lista flat com entradas separadas pra IA parear.
    for nm in nomes:
        partes.append({
            "nome": nm.title(),
            "documento": None,
            "papel": "Reu",
            "advogados": [],
            "pareamento_mecanico": "nome_isolado",
        })
    for cn in cnpjs:
        partes.append({
            "nome": None,
            "documento": cn,
            "papel": "Reu",
            "advogados": [],
            "pareamento_mecanico": "cnpj_isolado",
        })
    return partes


def _extract_data_protocolo(text: str) -> Optional[str]:
    """Extrai data de protocolo do carimbo invertido do eSAJ TJSP.

    Cada componente da data está INVERTIDO individualmente (não apenas
    o layout). Ex.: "5202/01/92" no texto = data real 29/10/2025:
      - "5202" → "2025" (ano invertido)
      - "01" → "10" (mês invertido)
      - "92" → "29" (dia invertido)

    Devolve no formato DD/MM/AAAA pra ficar consistente com o resto
    do sistema.
    """
    match = _RE_DATA_PROTOCOLO.search(text)
    if not match:
        return None
    yyyy_rev, mm_rev, dd_rev = match.group(1), match.group(2), match.group(3)
    try:
        yyyy = yyyy_rev[::-1]
        mm = mm_rev[::-1]
        dd = dd_rev[::-1]
        # Sanity: ano 19xx/20xx, mês 01-12, dia 01-31
        if not (1900 <= int(yyyy) <= 2099):
            return None
        if not (1 <= int(mm) <= 12):
            return None
        if not (1 <= int(dd) <= 31):
            return None
        return f"{dd}/{mm}/{yyyy}"
    except (ValueError, IndexError):
        return None


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
