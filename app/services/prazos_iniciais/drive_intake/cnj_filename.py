"""Extração tolerante do número do CNJ a partir do NOME do arquivo.

O operador nomeia o PDF com o número do processo; a gente lê daqui —
determinístico, não depende do texto (OCR) do PDF.

Tolerante a como o número costuma ser digitado:
  - mascarado:    "0001234-56.2024.8.05.0001"
  - dígitos crus: "00012345620248050001"
  - com texto/versão em volta: "Proc 0001234-56.2024.8.05.0001 (1).pdf"

NÃO valida dígito verificador de propósito (modo tolerante). A existência
real do processo é confirmada depois no lookup do Legal One.
"""
from __future__ import annotations

import re

# CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO  →  7 + 2 + 4 + 1 + 2 + 4 = 20 dígitos.
# Separadores OPCIONAIS e variados ENTRE os grupos (-, ., espaço, _), pra
# casar tanto a máscara oficial quanto o que o operador acaba digitando.
# `(?<!\d)`/`(?!\d)` garantem que não estamos pegando um pedaço de um número
# maior (telefone, id, etc.).
_SEP = r"[\s._-]*"
_CNJ_MASKED_RE = re.compile(
    r"(?<!\d)(\d{7})" + _SEP + r"(\d{2})" + _SEP + r"(\d{4})"
    + _SEP + r"(\d)" + _SEP + r"(\d{2})" + _SEP + r"(\d{4})(?!\d)"
)
# Rede de segurança: 20 dígitos colados, isolados por não-dígito.
_CNJ_RAW_RE = re.compile(r"(?<!\d)(\d{20})(?!\d)")


def extract_cnj_digits(filename: str | None) -> str | None:
    """Retorna os 20 dígitos do CNJ achado no nome do arquivo, ou ``None``.

    Pega o PRIMEIRO candidato. Primeiro tenta a forma com grupos (casa
    máscara E dígitos crus); se falhar, tenta 20 dígitos colados.
    """
    if not filename:
        return None
    m = _CNJ_MASKED_RE.search(filename)
    if m:
        return "".join(m.groups())
    m = _CNJ_RAW_RE.search(filename)
    if m:
        return m.group(1)
    return None


def mask_cnj(digits: str) -> str:
    """Formata 20 dígitos na máscara oficial NNNNNNN-DD.AAAA.J.TR.OOOO.

    Pra exibição/auditoria. Levanta ValueError se não forem 20 dígitos.
    """
    if not digits or len(digits) != 20 or not digits.isdigit():
        raise ValueError(f"Esperado 20 dígitos do CNJ, recebido: {digits!r}")
    return (
        f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}"
        f".{digits[13:14]}.{digits[14:16]}.{digits[16:20]}"
    )
