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

# ─── Carimbo invertido do eSAJ TJSP (barra lateral rotacionada 180°) ──
# O eSAJ Pasta Digital tem uma barra lateral em cada página com o carimbo
# de assinatura digital + URL de conferência. O pdfplumber não sabe ler
# texto rotacionado e devolve o conteúdo INVERTIDO caractere a caractere.
#
# Padrão observado (em 2 PDFs reais — calibrado contra TJSP):
#   .NNNNNNNNNNNNNNNNNNNN          ← código numérico do processo invertido
#   oremún                          ← "número" reverso
#   o
#   bos                             ← "sob" reverso
#   ,
#   HH:MM
#   sà                              ← "às" reverso
#   AAAA/MM/DD                      ← data invertida (já fica no formato YYYY/MM/DD por casualidade)
#   me                              ← "em" reverso
#   odalocotorp                     ← "protocolado" reverso
#   ,oluaP oaS ed odatsE od acitsuJ ed lanubirT e
#   <NOME EM CAIXA ALTA, INVERTIDO>
#   rop etnemlatigid odanissa       ← "assinado digitalmente por" reverso
#   ,lanigiro od aipóc é otnemucod etsE
#   .<código alfanumérico>          ← código de validação
#   ogidóc e                        ← "e código" reverso
#   <CNJ invertido>
#   ossecorp o emrofni              ← "informe o processo" reverso
#   ,od.otnemucoDaicnerefnoCrirba/gp/latigidatsap/rb.suj.psjt.jase//:sptth
#   etis o esseca
#   ,lanigiro o rirefnoc araP       ← "Para conferir o original," reverso (último token)
#
# Estratégia: detectar a âncora `araP` (= "Para" reverso, último token do
# bloco) e remover do início do bloco (~30 linhas atrás) até ela.
# Usamos a sequência única `,lanigiro\s+o\s+rirefnoc\s+araP` como âncora
# final e ancoramos no início com a sequência `oremún\s+o\s+bos` (= "sob
# o número" reverso), que é estável e inicia o bloco.

_RE_CARIMBO_INVERTIDO_ESAJ = re.compile(
    # Tudo entre "oremún\no\nbos" e "araP" (com Para nas variações de
    # caps que podem aparecer). re.DOTALL pra atravessar \n.
    r"oremún\s*\n\s*o\s*\n\s*bos[\s\S]+?\baraP\b",
    re.IGNORECASE,
)

# Caso o bloco esteja parcial (ex.: corte na truncagem) — remover linhas
# residuais reconhecíveis isoladamente:
_RE_CARIMBO_RESIDUAL = re.compile(
    r"^\s*(oremún|odalocotorp|me|odanissa|etnemlatigid|otnemucod|etsE|"
    r"lanigiro|aipóc|ogidóc|ossecorp|emrofni|etis|esseca|rirefnoc|araP|"
    r"oluaP|oaS|odatsE|acitsuJ|lanubirT)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# URL invertida do eSAJ (`rb.suj.psjt.jase//:sptth` etc.)
_RE_URL_ESAJ_INVERTIDA = re.compile(
    r"^\s*[,]?od\.otnemucoDaicnerefnoCrirba/gp/latigidatsap/rb\.suj\.[a-z]{2,4}jt\.jase//:sptth\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# URL normal do eSAJ (não invertida) — costuma aparecer em assinaturas
# digitais e cabeçalhos. Já temos _RE_URL_VALIDACAO mas só pega URLs
# isoladas na linha; aqui adicionamos uma variante mais permissiva pra
# pegar URLs concatenadas com outro texto:
_RE_URL_ESAJ_PASTADIGITAL = re.compile(
    r"https?://esaj\.[a-z]{2,4}jt\.jus\.br/pastadigital/[^\s]*",
    re.IGNORECASE,
)

# Códigos de validação isolados (`.FlJPfMe0`, `.XrYy9Xqi`, etc.)
# Pattern: ponto inicial + 5-12 chars alfanuméricos misturados.
_RE_CODIGO_VALIDACAO_ESAJ = re.compile(
    r"^\s*\.[a-zA-Z0-9]{5,12}\s*$",
    re.MULTILINE,
)

# CNJ invertido (ex.: `3500.62.8.5202.47-6186211`)
# Pattern: dígitos.dígitos.dígitos.dígitos.dígitos-dígitos (formato espelhado)
_RE_CNJ_INVERTIDO = re.compile(
    r"^\s*\d{4}\.\d{2}\.\d\.\d{4}\.\d{2}-\d{7}\s*$",
    re.MULTILINE,
)


# ─── Header repetido (heurística genérica) ─────────────────────────
# Cabeçalho do escritório/firma costuma aparecer em CADA página da peça.
# Padrão típico: 1-3 linhas curtas (<60 chars) em CAIXA ALTA OU mistura
# Title Case repetindo várias vezes.
# Estratégia: contar ocorrências e remover linhas que aparecem ≥5x no
# texto inteiro e têm <80 chars (não pega parágrafos legítimos).


def _strip_repeated_short_lines(text: str, min_repeats: int = 5,
                                max_len: int = 80) -> str:
    """Remove linhas curtas que se repetem N+ vezes (cabeçalho/footer).

    Conservador:
      - só remove linhas com <= max_len caracteres (não pega parágrafos)
      - precisa repetir min_repeats+ vezes
      - linhas vazias e numéricas puras não contam
    """
    from collections import Counter
    lines = text.split("\n")
    stripped_lines = [ln.strip() for ln in lines]
    counter = Counter(
        ln for ln in stripped_lines
        if ln and len(ln) <= max_len and not ln.isdigit()
    )
    blacklist = {ln for ln, n in counter.items() if n >= min_repeats}
    if not blacklist:
        return text
    out = [ln for ln, s in zip(lines, stripped_lines) if s not in blacklist]
    return "\n".join(out)


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

    # Carimbo invertido do eSAJ (barra lateral rotacionada) — ALVO PRIMEIRO
    # porque é um bloco grande (~30 linhas) e remover ele cedo simplifica
    # o restante. re.DOTALL é implícito pelo padrão.
    text = _RE_CARIMBO_INVERTIDO_ESAJ.sub("", text)
    text = _RE_URL_ESAJ_INVERTIDA.sub("", text)
    text = _RE_URL_ESAJ_PASTADIGITAL.sub("", text)
    text = _RE_CODIGO_VALIDACAO_ESAJ.sub("", text)
    text = _RE_CNJ_INVERTIDO.sub("", text)
    text = _RE_CARIMBO_RESIDUAL.sub("", text)

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

    # Header/footer repetido por página (escritório, endereço, telefone).
    # Heurística genérica: linhas curtas que aparecem 5+ vezes no doc.
    # Aplicado APÓS as regex de carimbo invertido pra não contar essas
    # linhas (já foram removidas).
    text = _strip_repeated_short_lines(text)

    # Reflow + colapso de linhas em branco
    text = _RE_REFLOW.sub(r"\1 \2", text)
    text = _RE_BLANK_LINES.sub("\n\n", text)

    # Normalização de espaços em cada linha + remoção de linhas vazias
    # nas pontas.
    lines = [ln.rstrip() for ln in text.split("\n")]
    return "\n".join(lines).strip()
