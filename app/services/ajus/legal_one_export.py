"""
Conversor de "Listagem de Ações Judiciais" (export bruto do Legal One)
para o formato da planilha de classificação do AJUS.

Detecta automaticamente o layout do export do L1 e devolve as linhas
no shape `XlsxRow` (mesma estrutura aceita pelo upload já existente),
preenchendo os defaults conforme o playbook do MDR:

  - Matéria                       = "Consumidor"
  - Risco/Probabilidade Perda     = "Remoto"
  - Justiça/Honorário             = "Juizado Especial Cível" se "Tipo de
                                     Ação" contiver "Juizado", senão
                                     "Justiça Comum"
  - UF vazia                      → inferida do segmento TR do CNJ
                                     (apenas Justiça Estadual, J=8)
  - Comarca vazia / "Não Informada" → preenchida com a capital da UF

Uso típico (no endpoint de upload):

    from app.services.ajus.legal_one_export import (
        is_legal_one_export,
        convert_legal_one_export_to_xlsx_rows,
    )

    if is_legal_one_export(ws):
        rows = convert_legal_one_export_to_xlsx_rows(ws)
    else:
        # ... validação dos cabeçalhos do template já existente ...
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from openpyxl.worksheet.worksheet import Worksheet

from app.services.ajus.classificacao_service import XlsxRow

__all__ = [
    "is_legal_one_export",
    "convert_legal_one_export_to_xlsx_rows",
    "LEGAL_ONE_EXPORT_HEADER_MARKERS",
]


# ── Constantes de domínio ──────────────────────────────────────────────

CAPITAIS_POR_UF: dict[str, str] = {
    "AC": "Rio Branco",
    "AL": "Maceió",
    "AM": "Manaus",
    "AP": "Macapá",
    "BA": "Salvador",
    "CE": "Fortaleza",
    "DF": "Brasília",
    "ES": "Vitória",
    "GO": "Goiânia",
    "MA": "São Luís",
    "MG": "Belo Horizonte",
    "MS": "Campo Grande",
    "MT": "Cuiabá",
    "PA": "Belém",
    "PB": "João Pessoa",
    "PE": "Recife",
    "PI": "Teresina",
    "PR": "Curitiba",
    "RJ": "Rio de Janeiro",
    "RN": "Natal",
    "RO": "Porto Velho",
    "RR": "Boa Vista",
    "RS": "Porto Alegre",
    "SC": "Florianópolis",
    "SE": "Aracaju",
    "SP": "São Paulo",
    "TO": "Palmas",
}

# Segmento TR do CNJ (5º grupo) → UF, apenas para Justiça Estadual (J=8).
# Fonte: Resolução CNJ 65/2008, Anexo VIII.
_CNJ_TR_ESTADUAL: dict[str, str] = {
    "01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA",
    "06": "CE", "07": "DF", "08": "ES", "09": "GO", "10": "MA",
    "11": "MT", "12": "MS", "13": "MG", "14": "PA", "15": "PB",
    "16": "PR", "17": "PE", "18": "PI", "19": "RJ", "20": "RN",
    "21": "RS", "22": "RO", "23": "RR", "24": "SC", "25": "SP",
    "26": "SE", "27": "TO",
}

_CNJ_RE = re.compile(
    r"^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$"
)

# Strings que devem ser tratadas como "vazio" em UF/Comarca da origem.
_PLACEHOLDERS_VAZIOS = {
    "",
    "nao informada",
    "nao informado",
    "n/a",
    "na",
    "-",
    "--",
    "none",
    "null",
}

# Cabeçalhos diagnósticos do export do L1 (normalizados sem acentos /
# minúsculas). Se >=3 destes aparecerem na primeira linha "preenchida"
# da planilha, consideramos que é o export bruto do L1 e disparamos a
# conversão automática.
LEGAL_ONE_EXPORT_HEADER_MARKERS: tuple[str, ...] = (
    "cod ajus",
    "numeros processo",
    "tipo de acao",
    "comarca",
    "uf",
    "risco/prob. perda",
    "materia",
)

# Posições das colunas que nos interessam dentro do export do L1.
# Mapeadas pelo nome de cabeçalho normalizado (sem acentos, lower) para
# evitar dependência de ordem fixa caso o L1 mude o layout.
_COLS_INTERESSE = (
    "numeros processo",
    "tipo de acao",
    "comarca",
    "uf",
)


# ── Helpers internos ──────────────────────────────────────────────────


def _strip_accents(value: str) -> str:
    """Remove acentos (NFD) — apenas para comparação de cabeçalhos."""
    nfkd = unicodedata.normalize("NFD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_header(value: object) -> str:
    if value is None:
        return ""
    return _strip_accents(str(value)).strip().lower()


def _is_placeholder(value: object) -> bool:
    if value is None:
        return True
    s = _strip_accents(str(value)).strip().lower()
    return s in _PLACEHOLDERS_VAZIOS


def _coerce_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _infer_uf_from_cnj(cnj: str) -> Optional[str]:
    """Devolve a UF a partir do CNJ se for Justiça Estadual (J=8)."""
    m = _CNJ_RE.match(cnj.strip())
    if not m:
        return None
    justica = m.group(4)
    tr = m.group(5)
    if justica != "8":
        return None
    return _CNJ_TR_ESTADUAL.get(tr)


def _normalize_justica_honorario(tipo_de_acao: object) -> str:
    """
    Mapeia "Tipo de Ação" do L1 para o domínio do AJUS:
      - contém "Juizado" → "Juizado Especial Cível"
      - caso contrário   → "Justiça Comum"
    """
    if tipo_de_acao is None:
        return "Justiça Comum"
    if "juizado" in str(tipo_de_acao).strip().lower():
        return "Juizado Especial Cível"
    return "Justiça Comum"


def _find_header_row(ws: Worksheet, max_scan: int = 5) -> Optional[tuple[int, list[str]]]:
    """
    Acha a linha de cabeçalho do export do L1.

    O export do Legal One costuma vir com a 1ª linha vazia (totalmente
    `None`) e os cabeçalhos na 2ª linha. Aceita até `max_scan` linhas
    iniciais pra ser robusto a pequenas variações (ex.: linha de título
    ou linha de filtros antes do header).

    Retorna `(row_index, headers_normalizados)` ou `None`.
    """
    for row_idx, raw in enumerate(
        ws.iter_rows(min_row=1, max_row=max_scan, values_only=True),
        start=1,
    ):
        if raw is None:
            continue
        norm = [_normalize_header(v) for v in raw]
        # Conta quantos marcadores conhecidos aparecem.
        hits = sum(1 for m in LEGAL_ONE_EXPORT_HEADER_MARKERS if m in norm)
        if hits >= 3:
            return row_idx, norm
    return None


def _column_indices(headers_norm: list[str]) -> dict[str, int]:
    """Mapeia cada cabeçalho de interesse pra seu índice na linha."""
    idx: dict[str, int] = {}
    for col in _COLS_INTERESSE:
        if col in headers_norm:
            idx[col] = headers_norm.index(col)
    return idx


# ── API pública ───────────────────────────────────────────────────────


def is_legal_one_export(ws: Worksheet) -> bool:
    """
    Heurística: a planilha é um export bruto do Legal One ("Listagem
    de Ações Judiciais") em vez do template do AJUS?

    Critério: pelo menos 3 dos cabeçalhos diagnósticos do L1 aparecem
    nas primeiras 5 linhas da aba ativa. Os cabeçalhos do template do
    AJUS (CNJ, UF, Comarca, Matéria, Justiça/Honorário, Risco/...) não
    batem com essa heurística porque o template não tem "Números
    Processo", "Tipo de Ação", "Cód AJUS" etc.
    """
    if ws is None:
        return False
    found = _find_header_row(ws)
    if not found:
        return False
    _, headers_norm = found
    # Garante que pelo menos as colunas que vamos USAR existem.
    cols = _column_indices(headers_norm)
    return "numeros processo" in cols and "tipo de acao" in cols


def convert_legal_one_export_to_xlsx_rows(
    ws: Worksheet,
) -> list[XlsxRow]:
    """
    Converte uma planilha de export bruto do L1 nas linhas que o
    `enqueue_from_xlsx_rows` espera, aplicando os defaults do MDR:

      - Matéria                       = "Consumidor"
      - Risco/Probabilidade Perda     = "Remoto"
      - Justiça/Honorário             = derivado de "Tipo de Ação"
      - UF vazia                      → inferida do CNJ
      - Comarca vazia / "Não Informada" → capital da UF

    Linhas sem CNJ são puladas (não tem como classificar). Linhas sem
    UF e sem possibilidade de inferir do CNJ também são puladas — caso
    contrário o item iria pra fila com UF vazia e travaria o runner.
    """
    found = _find_header_row(ws)
    if not found:
        # Defesa em profundidade — quem chama deve ter validado com
        # `is_legal_one_export` antes. Mas se chegou aqui sem header,
        # devolvemos lista vazia em vez de explodir.
        return []
    header_row_idx, headers_norm = found
    cols = _column_indices(headers_norm)

    col_cnj = cols.get("numeros processo")
    col_tipo = cols.get("tipo de acao")
    col_comarca = cols.get("comarca")
    col_uf = cols.get("uf")

    if col_cnj is None or col_tipo is None:
        return []

    rows: list[XlsxRow] = []
    for raw in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if raw is None:
            continue
        if all((v is None or str(v).strip() == "") for v in raw):
            continue

        cnj = _coerce_str(raw[col_cnj]) if col_cnj < len(raw) else ""
        if not cnj:
            continue

        uf = ""
        if col_uf is not None and col_uf < len(raw) and not _is_placeholder(raw[col_uf]):
            uf = str(raw[col_uf]).strip().upper()
        if not uf:
            inferred = _infer_uf_from_cnj(cnj)
            if inferred:
                uf = inferred
        if not uf:
            # Sem UF e sem como inferir → não dá pra classificar com
            # qualidade. Pula em silêncio (o operador veria a linha
            # ausente no resumo, e isso é melhor que enqueuear lixo).
            continue

        comarca: str
        if (
            col_comarca is None
            or col_comarca >= len(raw)
            or _is_placeholder(raw[col_comarca])
        ):
            comarca = CAPITAIS_POR_UF.get(uf, "")
        else:
            comarca = str(raw[col_comarca]).strip()

        tipo = raw[col_tipo] if col_tipo < len(raw) else None
        justica = _normalize_justica_honorario(tipo)

        rows.append(
            XlsxRow(
                cnj_number=cnj,
                uf=uf,
                comarca=comarca or None,
                matter="Consumidor",
                justice_fee=justica,
                risk_loss_probability="Remoto",
            )
        )

    return rows
