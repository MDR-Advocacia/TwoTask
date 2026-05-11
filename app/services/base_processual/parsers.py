"""Parsers tolerantes pra os dados que vem do XLSX de Listagem de Acoes.

A planilha vem do Legal One Reports. Encoding e formato podem variar
(pt-BR com acentos, decimais '1.500,00' ou '1500.00' ou 'R$ 1.500,00',
datas '00/00/0000' como NULL, etc). Helpers aqui sao defensivos por design.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional


_CNJ_DIGITS_RE = re.compile(r"[^0-9]")
_DEC_CLEAN_RE = re.compile(r"[^0-9,.\-]")
# Bloco de parte: "Nome: ...\nCNPJCPF: ..." (CNPJCPF pode vir vazio)
_PARTE_BLOCK_RE = re.compile(
    r"Nome:\s*(?P<nome>[^\n\r]*)\s*(?:\n|\r\n)\s*CNPJCPF:\s*(?P<doc>[^\n\r]*)",
    re.IGNORECASE,
)


def normalize_str(value) -> Optional[str]:
    """Strip, vazio -> None. 'nan' (pandas) -> None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def parse_cnj_digits(value) -> Optional[str]:
    """Extrai so os digitos do CNJ. None se vazio. Nao valida tamanho."""
    s = normalize_str(value)
    if not s:
        return None
    only_digits = _CNJ_DIGITS_RE.sub("", s)
    return only_digits if only_digits else None


def format_cnj_mask(only_digits: Optional[str]) -> Optional[str]:
    """Aplica mascara NNNNNNN-DD.AAAA.J.TR.OOOO em CNJ de 20 digitos.

    Se nao tiver exatamente 20 digitos, retorna o input cru — preserva
    valores legados sem corromper.
    """
    if not only_digits or len(only_digits) != 20:
        return only_digits
    return (
        f"{only_digits[0:7]}-{only_digits[7:9]}.{only_digits[9:13]}."
        f"{only_digits[13]}.{only_digits[14:16]}.{only_digits[16:20]}"
    )


def parse_decimal_br(value) -> Optional[Decimal]:
    """Parser tolerante de decimal pt-BR.

    Aceita: 0, '0', '1500', '1500.00', '1.500,00', 'R$ 1.500,00', '', None,
    int/float/Decimal direto. Retorna None se vazio ou nao parseavel.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        # preserva precisao via string repr (evita 1500.0 -> Decimal('1500.0'))
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    cleaned = _DEC_CLEAN_RE.sub("", s)
    if not cleaned or cleaned in {"-", ",", ".", "-.", "-,"}:
        return None
    has_comma = "," in cleaned
    has_dot = "." in cleaned
    if has_comma and has_dot:
        # pt-BR: '1.500,00' -> '1500.00'
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif has_comma:
        # so virgula -> assume pt-BR ('1500,00' -> '1500.00')
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date_br(value) -> Optional[datetime]:
    """Parser de data/timestamp pt-BR.

    Aceita 'dd/mm/aaaa', 'dd/mm/aaaa HH:MM:SS', '00/00/0000 ...' (= NULL),
    datetime/date direto, vazio. Sempre retorna datetime ou None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    if not s:
        return None
    # Convencao do export L1: 00/00/0000 = NULL
    if s.startswith("00/00/0000"):
        return None
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_date_only_br(value) -> Optional[date]:
    """Variante que retorna so date (sem hora). Usado pra 'Distribuido em'."""
    dt = parse_date_br(value)
    if dt is None:
        return None
    return dt.date()


def parse_bool_sim_nao(value) -> Optional[bool]:
    """'Sim' -> True, 'Nao' -> False, vazio -> None."""
    s = normalize_str(value)
    if s is None:
        return None
    norm = s.lower().replace("ã", "a").replace("ç", "c")
    if norm in {"sim", "s", "yes", "true", "1"}:
        return True
    if norm in {"nao", "n", "no", "false", "0"}:
        return False
    return None


def parse_partes_bloco(value) -> list[dict]:
    """Extrai lista [{"nome", "documento"}] do bloco multi-linha do L1.

    Formato:
        Nome: Joao da Silva
        CNPJCPF: 123.456.789-00

        Nome: Maria Souza
        CNPJCPF:

    Fallback: se nao casar regex, guarda o texto inteiro como nome.
    Retorna [] se vazio.
    """
    if value is None:
        return []
    s = str(value)
    if not s.strip():
        return []
    out: list[dict] = []
    for m in _PARTE_BLOCK_RE.finditer(s):
        nome = m.group("nome").strip()
        doc = m.group("doc").strip()
        if not nome and not doc:
            continue
        out.append({"nome": nome or None, "documento": doc or None})
    if not out:
        cleaned = s.strip()
        if cleaned:
            out.append({"nome": cleaned, "documento": None})
    return out


def parse_int(value) -> Optional[int]:
    """Int tolerante (campos como 'Dias Ult Atualizacao' as vezes vem string)."""
    if value is None:
        return None
    if isinstance(value, bool):
        # bool e' subclass de int — rejeita pra evitar True/False virarem 1/0 silenciosamente
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(value)
        except (ValueError, OverflowError):
            return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None
