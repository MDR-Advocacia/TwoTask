"""
Extractor pra PDFs do TJSP exportados via "Pasta Digital eSAJ" com capa
estilo eproc adicionada (formato CAPA PROCESSO sintética).

Diferenças críticas vs eproc real (TJRS/TRF):
  * Separador de docs: ``PÁGINA DE SEPARAÇÃO`` + ``Evento N`` (não
    ``Documento N``).
  * Cabeçalho do bloco: ``Evento:\\n<desc>\\nData:\\n<dd/mm/aaaa hh:mm:ss>
    \\nUsuário:\\n<sigla - nome>``  — sem o campo ``Tipo documento:``
    intermediário.
  * Layout 2-colunas em "Partes e Representantes" — Banco Master
    aparece quebrado em duas linhas:
        ``BANCO MASTER S/A - EM LIQUIDACAO``
        ``EXTRAJUDICIAL (CNPJ) - Pessoa Jurídica``
  * Valor da Causa quebrado entre rótulo e valor por largura de coluna:
        ``Valor da Causa: R$ Nível de Sigilo do Sem Sigilo (Nível``
        ``10.000,00 Processo: 0)``
  * Justiça Gratuita pode aparecer como ``Requerida`` (não só
    ``Deferida/Indeferida``).
  * Header do conteúdo do INIC1 traz ``Processo CNJ/UF, Evento 1, INIC1,
    Página N`` em cada página — boilerplate ignorável.

Sempre devolvemos ``texto_cru`` na integra (truncado em ~200k chars)
mesmo quando a timeline foi extraída — o classificador AJUS depende
disso pra ler a petição inicial completa, e o eproc original deixava
isso de fora (causa raiz do bug "timeline=[], integra vazia").
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


# ─── CNJ ───────────────────────────────────────────────────────────
_RE_CNJ = re.compile(r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})")


# ─── Capa ──────────────────────────────────────────────────────────
_RE_CLASSE = re.compile(r"^\s*Classe\s+da\s+ação:\s*(.+?)\s*$", re.MULTILINE)
_RE_ORGAO = re.compile(r"^\s*Órgão\s+Julgador:\s*(.+?)\s*$", re.MULTILINE)
_RE_AUTUACAO = re.compile(r"Data\s+de\s+autuação:\s*(\d{2}/\d{2}/\d{4})")

# Valor da Causa no TJSP é renderizado em layout de 3 colunas das
# "Informações Adicionais", então o rótulo e o valor podem ficar em
# linhas diferentes:
#     Valor da Causa: R$ Nível de Sigilo do Sem Sigilo (Nível
#     10.000,00 Processo: 0)
# Estratégia: aceita o valor logo depois de "R$" OU em até ~150 chars
# de distância (atravessa quebra de linha + texto da coluna seguinte).
# `[\s\S]` em vez de `.` pra deixar o `?` lazy parar no 1º monetário
# `\d+(?:\.\d+)*,\d{2}`, pulando o ruído ("Nível de Sigilo do Sem...").
_RE_VALOR = re.compile(
    r"Valor\s+da\s+Causa:\s*R\$[\s\S]{0,150}?([\d.]+,\d{2})",
)

# Aceita Deferida/Indeferida/Requerida/Não há pedido — o TJSP usa
# "Requerida" no momento da distribuição (antes do despacho de
# deferimento), enquanto o eproc original já traz "Deferida".
_RE_GRATUITA = re.compile(
    r"Justiça\s+Gratuita:\s*(Deferida|Indeferida|Requerida|Não\s+há\s+pedido)",
    re.IGNORECASE,
)

# "Nível de Sigilo do Processo: Sem Sigilo (Nível 0)" → captura tudo
# após o ":". O rótulo no TJSP pode vir partido em colunas, então
# casamos com lookahead permissivo.
_RE_SIGILO = re.compile(
    r"Nível\s+de\s+Sigilo[^:]*:\s*([^\n]+)",
    re.IGNORECASE,
)

_RE_ASSUNTOS_BLOCO = re.compile(
    r"Assuntos\s*\n\s*Código\s+Descrição\s+Principal\s*\n(.+?)"
    r"(?=Partes\s+e\s+Representantes)",
    re.DOTALL,
)
# Códigos do TJSP variam de 6 a 10 dígitos (061202, 06040102, 0218020101).
_RE_LINHA_ASSUNTO = re.compile(
    r"^\s*(\d{4,10})\s+(.+?)\s+(Sim|Não)\s*$",
    re.MULTILINE,
)


# ─── Partes ────────────────────────────────────────────────────────
# Em "Partes e Representantes" o pdfplumber NÃO consegue separar as 2
# colunas (AUTOR | RÉU) limpo: às vezes a coluna direita aparece
# colada no fim da linha esquerda; às vezes vem em linha separada com
# o nome PJ partido entre 2 linhas. Pra reconstruir o polo passivo, o
# extractor faz 3 passos antes do regex principal:
#   (1) `_split_2col_pj_lines`: detecta padrão "<CONT_PJ> (CNPJ) -
#       Pessoa Jurídica" no MEIO de uma linha (caso PDF #1: parte da
#       coluna direita coladada no fim da esquerda) e separa em linha
#       própria.
#   (2) `_join_pj_continuations`: junta linhas que COMEÇAM com palavra
#       de continuação (EXTRAJUDICIAL, FALÊNCIA...) com a linha anterior
#       (que tem o início do nome PJ).
#   (3) Heurística no destino: quando há UMA parte na linha (layout
#       vertical do TJSP), Pessoa Jurídica → polo passivo, Pessoa
#       Física → polo ativo. Quando há DUAS partes na linha (layout
#       horizontal idx=0 ativo / idx=1 passivo), preserva a ordem.
_PJ_CONTINUATION = (
    "EXTRAJUDICIAL",
    "FALÊNCIA",
    "FALENCIA",
    "RECUPERAÇÃO",
    "RECUPERACAO",
    "JUDICIAL",
)

_RE_PARTE_LINHA = re.compile(
    r"([A-ZÀ-Ú][A-ZÀ-Ú0-9\s./&\-']+?)\s*"
    r"\((\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\)\s*-\s*"
    r"Pessoa\s+(Física|Jurídica)",
)
_RE_PROCURADOR = re.compile(
    r"([A-ZÀ-Ú][A-ZÀ-Ú\s\-']+?)\s+([A-Z]{2}\d{4,7})\b",
)
# Detecta a "cauda" de uma PJ (continuação + CNPJ + Pessoa Jurídica)
# em qualquer posição da linha — usada pra separar layout 2-cols onde
# pdfplumber colou as colunas.
_RE_PJ_TAIL = re.compile(
    r"\b("
    + "|".join(_PJ_CONTINUATION)
    + r")\s+(\(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\))\s*-\s*"
    + r"Pessoa\s+Jurídica",
    re.IGNORECASE,
)
# Linha que termina em OAB (advogado isolado da coluna esquerda) —
# usada pra pular essa linha quando procuramos a linha do "início PJ"
# pra grudar a cauda.
_RE_LINHA_ADVOGADO_OAB = re.compile(r"\b[A-Z]{2}\d{4,7}\s*$")


# ─── Timeline (TJSP-específico) ────────────────────────────────────
# TJSP separa eventos com:
#     PÁGINA DE SEPARAÇÃO
#     (Gerada automaticamente pelo sistema.)
#     Evento N
#     Evento:
#     <DESCRIÇÃO_DO_EVENTO>
#     Data:
#     DD/MM/AAAA HH:MM:SS
#     Usuário:
#     <SIGLA - NOME>
_RE_EVENTO_INICIO = re.compile(r"^\s*Evento\s+(\d+)\s*$", re.MULTILINE)
_RE_EVENTO_METADATA = re.compile(
    r"Evento:\s*\n\s*(.+?)\s*\n"
    r"Data:\s*\n\s*(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}:\d{2}\s*\n"
    r"Usuário:\s*\n\s*(.+?)\s*\n",
    re.DOTALL,
)


MAX_INTEGRA_CHARS = 200_000


class TjspEprocExtractor(BaseExtractor):
    name = "tjsp_eproc_v1"

    def extract(self, pages: List[str]):
        from app.services.prazos_iniciais.pdf_extractor import ExtractionResult

        full_text = "\n".join(pages)
        cnj = _extract_cnj(full_text)
        tribunal = tribunal_from_cnj(cnj) if cnj else None

        # Capa: pgs 1 (carimbo) + 2-3 (capa formal). Concat 4 pra cobrir
        # variações com mais campos opcionais.
        capa_text = "\n".join(pages[:4]) if pages else ""
        capa = _extract_capa(capa_text, tribunal=tribunal)

        timeline = _extract_timeline(full_text)

        # texto_cru SEMPRE presente — fallback crítico pro classificador
        # AJUS quando a timeline não tem detalhe suficiente (petição
        # inicial, declaração de pobreza, contrato, etc).
        texto_cru = (
            full_text[:MAX_INTEGRA_CHARS]
            if len(full_text) > MAX_INTEGRA_CHARS
            else full_text
        )

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

        integra: dict = {"texto_cru": texto_cru}
        if timeline:
            integra["timeline"] = timeline

        return ExtractionResult(
            success=True,
            extractor_used=self.name,
            confidence=confidence,
            capa_json=capa,
            integra_json=integra,
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
        # Deferida/Requerida → True (presente/concedida); Indeferida/
        # "Não há pedido" → False.
        valor = m.group(1).strip().lower()
        capa["justica_gratuita"] = valor in ("deferida", "requerida")

    m = _RE_SIGILO.search(capa_text)
    if m:
        capa["segredo_justica"] = "sem sigilo" not in m.group(1).strip().lower()

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


def _split_2col_pj_lines(bloco: str) -> str:
    """
    Em layout 2-colunas do TJSP, a continuação do nome de PJ do polo
    direito pode aparecer COLADA com texto da coluna esquerda (a parte
    autora ou um advogado). Exemplos reais:

      MARCIA ... (CPF) - Pessoa Física EXTRAJUDICIAL (CNPJ) - Pessoa Jurídica
      ALEXIA ... MG226652 EXTRAJUDICIAL (CNPJ) - Pessoa Jurídica

    Detecta o padrão "<CONT_PJ> (CNPJ) - Pessoa Jurídica" no MEIO da
    linha e separa em duas: (a) tudo antes da continuação fica na
    coluna esquerda; (b) "<CONT_PJ> (CNPJ) - Pessoa Jurídica" vai pra
    linha nova, que `_join_pj_continuations` então junta com a linha
    anterior (que tem o início do nome PJ).
    """
    out_lines: List[str] = []
    for line in bloco.splitlines():
        m = _RE_PJ_TAIL.search(line)
        if m and m.start() > 0 and line[: m.start()].strip():
            esquerda = line[: m.start()].rstrip()
            direita = line[m.start():]
            out_lines.append(esquerda)
            out_lines.append(direita)
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def _join_pj_continuations(bloco: str) -> str:
    """
    Quando uma PJ tem nome muito longo (ex.: 'BANCO MASTER S/A - EM
    LIQUIDACAO'), o eSAJ quebra a linha e a continuação cai numa linha
    posterior, ANTES do '(CNPJ) - Pessoa Jurídica'. Procura a "cauda"
    numa linha (após `_split_2col_pj_lines`) e gruda na linha do
    "início PJ" — que é a primeira linha PRA TRÁS que NÃO seja:
      - parte já completa (`_RE_PARTE_LINHA` casa)
      - advogado isolado (linha terminando em OAB)
      - header simples ("AUTOR RÉU", "Partes e Representantes", etc.)
      - linha em branco

    Sem essa heurística, a junção naïve gruda a cauda na linha errada
    (a parte do polo ativo ou um advogado), em PDFs onde o pdfplumber
    interleavou as colunas — caso real dos PDFs do TJSP.
    """
    HEADERS = {
        "AUTOR RÉU", "AUTOR", "RÉU",
        "Partes e Representantes",
        "Procurador(es):", "Procuradores:",
    }
    lines = bloco.splitlines()
    result: List[str] = []
    for line in lines:
        stripped = line.strip()
        is_cauda = (
            any(stripped.startswith(kw) for kw in _PJ_CONTINUATION)
            and "(" in stripped
            and "Pessoa" in stripped
        )
        if is_cauda and result:
            target_idx = None
            for j in range(len(result) - 1, -1, -1):
                cand = result[j].strip()
                if not cand:
                    continue
                if cand in HEADERS:
                    continue
                if _RE_PARTE_LINHA.search(cand):
                    continue  # parte já completa — pula
                if _RE_LINHA_ADVOGADO_OAB.search(cand):
                    continue  # advogado isolado — pula
                target_idx = j
                break
            if target_idx is not None:
                result[target_idx] = result[target_idx].rstrip() + " " + stripped
                continue  # consumiu a cauda; não append
        result.append(line)
    return "\n".join(result)


def _extract_partes(capa_text: str) -> tuple[list[dict], list[dict]]:
    polo_ativo: list[dict] = []
    polo_passivo: list[dict] = []

    inicio = capa_text.find("Partes e Representantes")
    fim = capa_text.find("Informações Adicionais")
    if inicio < 0:
        return polo_ativo, polo_passivo
    if fim < 0:
        fim = len(capa_text)
    bloco = capa_text[inicio:fim]

    # 1. Junta CPF/CNPJ partido por largura ("(NN.NNN.NNN/NNNN-\nNN)").
    bloco = re.sub(
        r"(\(\d[\d./\-]*?)\n([\d./\-]+?\))",
        r"\1\2",
        bloco,
    )
    # 2. Quebra layout 2-cols onde pdfplumber colou as colunas (parte
    #    da coluna direita encostada no fim da linha esquerda).
    bloco = _split_2col_pj_lines(bloco)
    # 3. Junta linhas de continuação de PJ (EXTRAJUDICIAL, FALÊNCIA...).
    bloco = _join_pj_continuations(bloco)

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
            # Decisão de polo:
            # - Múltiplas partes na MESMA linha (layout horizontal: a
            #   tabela "AUTOR | RÉU" foi capturada de fato em 2 colunas)
            #   → idx=0 = ativo, idx=1+ = passivo. Preserva a ordem.
            # - Única parte na linha (layout vertical, comum no TJSP
            #   pós-pdfplumber) → usa o tipo de pessoa pra decidir:
            #   Pessoa Jurídica = passivo, Pessoa Física = ativo.
            #   Funciona pro caso MDR (consumidor x banco). Em PF x PF
            #   ou PJ x PJ a heurística erra e o operador corrige no
            #   HITL — caso raro nos uploads atuais.
            if len(partes_na_linha) > 1:
                destino = polo_ativo if idx == 0 else polo_passivo
            else:
                destino = (
                    polo_passivo
                    if tipo_pessoa.lower().startswith("jur")
                    else polo_ativo
                )
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
    Segmenta por ``Evento N`` (linha isolada após PÁGINA DE SEPARAÇÃO).
    Pra cada bloco, tenta extrair descrição/data/usuário do cabeçalho
    ``Evento:\\n<desc>\\nData:\\n<...>\\nUsuário:\\n<...>``.
    """
    matches = list(_RE_EVENTO_INICIO.finditer(full_text))
    if not matches:
        return []

    timeline: list[dict] = []

    for i, m in enumerate(matches):
        evento_id = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        bloco = full_text[start:end]

        meta_match = _RE_EVENTO_METADATA.search(bloco[:1200])
        descricao: Optional[str] = None
        protocol_date_iso: Optional[str] = None
        if meta_match:
            descricao = _normalize_inline(meta_match.group(1))
            d = _parse_data_brasileira(meta_match.group(2))
            if d:
                protocol_date_iso = d.isoformat()

        cleaned = clean_document_text(bloco)

        label = (
            f"{evento_id} - {descricao}"
            if descricao
            else _derive_label(cleaned, evento_id)
        )

        timeline.append({
            "document_id": int(evento_id),
            "label": label[:160],
            "protocol_date": protocol_date_iso,
            "timeline_date": protocol_date_iso,
            "document_text": cleaned,
            "document_kind": None,
        })

    return timeline


def _derive_label(text: str, evento_id: str) -> str:
    if not text:
        return f"Evento {evento_id}"
    for line in text.splitlines():
        s = line.strip()
        if len(s) >= 4 and not s.isdigit():
            return f"{evento_id} - {s[:120]}"
    return f"Evento {evento_id}"
