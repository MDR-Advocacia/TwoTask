"""Catalogo de regex pra deteccao de eventos no texto do andamento.

Cada andamento e' confrontado contra todos os padroes. Um mesmo
andamento pode disparar varios achados (ex.: texto que fala em
"sentenca" + "arquivamento" gera 2 registros).

Lista pt-BR explicita, case-insensitive, sem dependencia de LLM.
Operador ajusta aqui conforme ve falsos positivos/negativos.
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple

from app.models.varredura import (
    EVENTO_ARQUIVAMENTO,
    EVENTO_AUDIENCIA_CANCELADA,
    EVENTO_AUDIENCIA_DESIGNADA,
    EVENTO_REVELIA,
    EVENTO_SENTENCA,
    EVENTO_TRANSITO_JULGADO,
)


class Pattern(NamedTuple):
    tipo: str
    label: str
    regex: re.Pattern


# Ordem importa apenas pra prioridade de exibicao no log — todos os
# matches sao registrados.
PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        tipo=EVENTO_AUDIENCIA_DESIGNADA,
        label="Audiencia designada/marcada",
        regex=re.compile(
            r"audi[êe]ncia[^.]*(designad[ao]|marcad[ao])",
            re.IGNORECASE,
        ),
    ),
    Pattern(
        tipo=EVENTO_AUDIENCIA_CANCELADA,
        label="Audiencia cancelada/adiada/redesignada",
        regex=re.compile(
            r"audi[êe]ncia[^.]*(cancelad[ao]|adiad[ao]|redesignad[ao])",
            re.IGNORECASE,
        ),
    ),
    Pattern(
        tipo=EVENTO_SENTENCA,
        label="Sentenca",
        regex=re.compile(r"senten[çc]a", re.IGNORECASE),
    ),
    Pattern(
        tipo=EVENTO_REVELIA,
        label="Revelia",
        regex=re.compile(r"revel(?:ia|izad[ao])", re.IGNORECASE),
    ),
    Pattern(
        tipo=EVENTO_TRANSITO_JULGADO,
        label="Transito em julgado",
        regex=re.compile(r"tr[âa]nsito\s+em\s+julgado", re.IGNORECASE),
    ),
    Pattern(
        tipo=EVENTO_ARQUIVAMENTO,
        label="Arquivamento",
        regex=re.compile(r"arquivad[ao]|arquivamento", re.IGNORECASE),
    ),
)


class Detection(NamedTuple):
    tipo: str
    matched_text: str


def detect_eventos(texto: str) -> list[Detection]:
    """Aplica todos os padroes no texto. Retorna 1 Detection por padrao
    que matchou (mesmo texto pode gerar varios)."""
    if not texto:
        return []
    out: list[Detection] = []
    for p in PATTERNS:
        m = p.regex.search(texto)
        if m:
            out.append(Detection(tipo=p.tipo, matched_text=m.group(0)))
    return out


def list_pattern_descriptions() -> list[dict[str, str]]:
    """Util pra UI mostrar os padroes ativos."""
    return [
        {"tipo": p.tipo, "label": p.label, "regex": p.regex.pattern}
        for p in PATTERNS
    ]
