"""
Limpeza mecânica de boilerplate em texto extraído de PDFs.

Alvos compartilhados entre os sistemas suportados (PJe, eproc, PROJUDI,
eSAJ):
- Carimbos de assinatura digital (multi-linha) — todos os sistemas:
    "Assinado (eletronicamente|digitalmente) por: ..."
    "Documento assinado..."
    URLs de validação (https://pje*.jus.br/..., https://esaj.*.jus.br/...,
    https://eproc*.jus.br/..., https://projudi.*.jus.br/...)
    "Número do documento: ...", "Código de validação..."
    "Este documento foi gerado pelo usuário ..."
- Marcadores de página: `Num. N - Pág. N` (PJe), `Id. N - Pág. N` (PROJUDI),
  `Página X de Y`, `fls. NN`.
- Cabeçalho do template repetido por documento (PJe): `Número:`, `Classe:`,
  `Órgão julgador:`, `TJBA`, `PJe - Processo Judicial Eletrônico`, etc.
- eproc: `PÁGINA DE SEPARAÇÃO`, `(Gerada automaticamente pelo sistema.)`
- PROJUDI: `Código de validação do documento: ...`,
  `TRIBUNAL DE JUSTIÇA DO ESTADO ...` no header repetido.

Tudo via regex. Quando não bater, deixa passar.
"""

from __future__ import annotations

import re

# ─── Carimbos de assinatura digital ────────────────────────────────
# Multi-linha: linha "Assinado eletronicamente por: ..." pode vir
# antes ou depois de URL/Número do documento. Removemos cada linha
# isoladamente — mais robusto que tentar capturar o bloco todo.

_RE_ASSINADO = re.compile(
    r"^\s*Assinado\s+(eletronicamente|digitalmente)\s+por:.*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_URL_PJE = re.compile(
    r"^\s*https?://pje\d?g?\.[^\s]+$",
    re.MULTILINE | re.IGNORECASE,
)
# eproc/PROJUDI/eSAJ — URLs de validação de assinatura
_RE_URL_VALIDACAO = re.compile(
    r"^\s*https?://(eproc|projudi|esaj)[^\s]+$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_CODIGO_VALIDACAO = re.compile(
    r"^\s*Código\s+de\s+validação\s+do\s+documento:.*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_NUM_DOCUMENTO = re.compile(
    r"^\s*Número\s+do\s+documento:.*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_GERADO_USUARIO = re.compile(
    r"^\s*Este\s+documento\s+foi\s+gerado\s+pelo\s+usuário.*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_DOC_ASSINADO_PREFIX = re.compile(
    r"^\s*Documento\s+assinado.*$",
    re.MULTILINE | re.IGNORECASE,
)

# ─── Marcadores de página ──────────────────────────────────────────
# `Num. NNNNN - Pág. N` é usado também como separador de docs pelo
# PJeTjbaExtractor — quando rodar limpeza DENTRO de um doc segmentado,
# já não vai existir. Rodar antes da segmentação remove os do meio.

_RE_NUM_PAG = re.compile(
    r"^\s*Num\.\s*\d+\s*-\s*P[áa]g\.\s*\d+\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_PAGINA_X_DE_Y = re.compile(
    r"^\s*Página\s+\d+\s+de\s+\d+\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_FLS = re.compile(
    r"^\s*fls?\.?\s*\d+\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# PROJUDI — `Id. NNNNN - Pág. N` (anchor da segmentação no extractor;
# remover apenas DENTRO de docs já segmentados)
_RE_ID_PAG_PROJUDI = re.compile(
    r"^\s*Id\.\s*\d+\s*-\s*P[áa]g\.\s*\d+\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# eproc — separador de documento (já consumido como anchor; remover
# resíduos)
_RE_PAGINA_SEPARACAO = re.compile(
    r"^\s*PÁGINA\s+DE\s+SEPARAÇÃO\s*$|"
    r"^\s*\(Gerada\s+automaticamente\s+pelo\s+sistema\.?\)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# Header repetido do PROJUDI / outros tribunais
_RE_TRIBUNAL_HEADER_LINHA = re.compile(
    r"^\s*TRIBUNAL\s+DE\s+JUSTIÇA\s+DO\s+ESTADO.*$|"
    r"^\s*PODER\s+JUDICIÁRIO\s*$|"
    r"^\s*PROJUDI\s*-\s*Processo\s+Judicial\s+Digital\s*$|"
    r"^\s*Baixado\s+do\s+PROJUDI\s+em:.*$",
    re.MULTILINE | re.IGNORECASE,
)

# ─── Cabeçalho de capa repetido ───────────────────────────────────
# Bloco que aparece no início de cada documento exportado do PJe.
# Em vez de capturar como bloco (frágil porque a ordem dos campos
# varia), removemos linha a linha cada um dos campos típicos quando
# aparecem isoladamente.

_RE_DATA_CABECALHO = re.compile(
    r"^\s*\d{2}/\d{2}/\d{4}\s*$", re.MULTILINE,
)
_RE_NUMERO_PROCESSO = re.compile(
    r"^\s*Número:\s*[\d.\-]+.*$", re.MULTILINE,
)
_RE_CLASSE_LINHA = re.compile(
    r"^\s*Classe:\s*[A-ZÀ-Ú\s/().,]+\s*$", re.MULTILINE,
)
_RE_ORGAO_LINHA = re.compile(
    r"^\s*Órgão\s+julgador(\s+colegiado)?:.*$", re.MULTILINE | re.IGNORECASE,
)
_RE_DISTRIB_LINHA = re.compile(
    r"^\s*Última\s+distribuição\s*:.*$", re.MULTILINE | re.IGNORECASE,
)
_RE_VALOR_LINHA = re.compile(
    r"^\s*Valor\s+da\s+causa:\s*R\$.*$", re.MULTILINE | re.IGNORECASE,
)
_RE_ASSUNTOS_LINHA = re.compile(
    r"^\s*Assuntos:.*$", re.MULTILINE | re.IGNORECASE,
)
_RE_SEGREDO_LINHA = re.compile(
    r"^\s*Segredo\s+de\s+justiça\?\s*(SIM|NÃO).*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_GRATUITA_LINHA = re.compile(
    r"^\s*Justiça\s+gratuita\?\s*(SIM|NÃO).*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_LIMINAR_LINHA = re.compile(
    r"^\s*Pedido\s+de\s+liminar.*$", re.MULTILINE | re.IGNORECASE,
)
_RE_TJBA_PJE = re.compile(
    r"^\s*TJBA\s*$|^\s*PJe\s*-\s*Processo\s+Judicial\s+Eletrônico\s*$",
    re.MULTILINE,
)
_RE_PARTES_ADVOGADOS = re.compile(
    r"^\s*Partes\s+Advogados\s*$", re.MULTILINE | re.IGNORECASE,
)
_RE_DOCUMENTOS_HEADER = re.compile(
    r"^\s*Documentos\s*$|^\s*Id\.\s*Data\s+da\s*$|^\s*Assinatura\s*$|^\s*Documento\s+Tipo\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# ─── Reflow ─────────────────────────────────────────────────────────
# Junta uma quebra de linha quando a próxima linha começa em minúscula
# (provável continuação de parágrafo). Conservador: não junta se a
# linha anterior termina em pontuação forte ou quebra em branco.

_RE_REFLOW = re.compile(r"([^\.\!\?\:\n])\n([a-záéíóúâêîôûãõç])")
_RE_BLANK_LINES = re.compile(r"\n{3,}")


def clean_document_text(text: str) -> str:
    """
    Aplica todas as limpezas mecânicas a um pedaço de texto (um documento
    individual já segmentado).
    """
    if not text:
        return text

    # Carimbos de assinatura (PJe, eproc, PROJUDI, eSAJ)
    text = _RE_ASSINADO.sub("", text)
    text = _RE_URL_PJE.sub("", text)
    text = _RE_URL_VALIDACAO.sub("", text)
    text = _RE_NUM_DOCUMENTO.sub("", text)
    text = _RE_CODIGO_VALIDACAO.sub("", text)
    text = _RE_GERADO_USUARIO.sub("", text)
    text = _RE_DOC_ASSINADO_PREFIX.sub("", text)

    # Marcadores de página
    text = _RE_NUM_PAG.sub("", text)
    text = _RE_ID_PAG_PROJUDI.sub("", text)
    text = _RE_PAGINA_X_DE_Y.sub("", text)
    text = _RE_FLS.sub("", text)
    text = _RE_PAGINA_SEPARACAO.sub("", text)
    text = _RE_TRIBUNAL_HEADER_LINHA.sub("", text)

    # Cabeçalho de capa repetido (linhas isoladas)
    text = _RE_DATA_CABECALHO.sub("", text)
    text = _RE_NUMERO_PROCESSO.sub("", text)
    text = _RE_CLASSE_LINHA.sub("", text)
    text = _RE_ORGAO_LINHA.sub("", text)
    text = _RE_DISTRIB_LINHA.sub("", text)
    text = _RE_VALOR_LINHA.sub("", text)
    text = _RE_ASSUNTOS_LINHA.sub("", text)
    text = _RE_SEGREDO_LINHA.sub("", text)
    text = _RE_GRATUITA_LINHA.sub("", text)
    text = _RE_LIMINAR_LINHA.sub("", text)
    text = _RE_TJBA_PJE.sub("", text)
    text = _RE_PARTES_ADVOGADOS.sub("", text)
    text = _RE_DOCUMENTOS_HEADER.sub("", text)

    # Reflow + colapso de linhas em branco
    text = _RE_REFLOW.sub(r"\1 \2", text)
    text = _RE_BLANK_LINES.sub("\n\n", text)

    # Normalização de espaços em cada linha + remoção de linhas vazias
    # nas pontas.
    lines = [ln.rstrip() for ln in text.split("\n")]
    return "\n".join(lines).strip()
