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
    EVENTO_CUMPRIMENTO_EXTINTO,
    EVENTO_CUMPRIMENTO_INICIADO,
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
    Pattern(
        tipo=EVENTO_CUMPRIMENTO_INICIADO,
        label="Cumprimento de sentença iniciado",
        regex=re.compile(
            r"cumprimento\s+de\s+senten[çc]a"
            r"|intim[ea][-\s]?se\s+.{0,50}\s*pa(ra|guem|gue)?\s*pag"
            r"|intim[ae][çc][ãa]o\s+(para|pa\.\s+)?pagamento"
            r"|bacenjud|sisbajud|renajud|infojud"
            r"|penhora\s+(online|de\s+ativos|sobre|determinada|de\s+valores)"
            r"|determin[ao]\s+(o\s+)?(bloqueio|penhora)"
            r"|bloqueio\s+(de\s+ativos|de\s+valores|judicial)"
            r"|indisponibilidade\s+de\s+ativos"
            r"|dep[óo]sito\s+judicial"
            r"|execu[çc][ãa]o\s+de\s+senten[çc]a\s+iniciad[ao]"
            r"|homologa[çc][ãa]o\s+(?:d[ao]\s+|d[ao]s\s+)?c[áa]lculos?"
            r"|alvar[áa]\s+(de|para)\s+levantamento"
            r"|art\.?\s*523\s+do\s+cpc"
            r"|requerimento\s+de\s+cumprimento",
            re.IGNORECASE,
        ),
    ),
    Pattern(
        tipo=EVENTO_CUMPRIMENTO_EXTINTO,
        label="Cumprimento extinto/satisfeito",
        regex=re.compile(
            r"extin[çc][ãa]o\s+d[ao]\s+execu[çc][ãa]o"
            r"|extint[ao]\s+(o\s+cumprimento|a\s+execu[çc][ãa]o)"
            r"|cumprimento\s+extint[ao]"
            r"|quita[çc][ãa]o\s+(integral|total|d[ao]\s+d[ée]bito)"
            r"|d[ée]bito\s+quitad[ao]"
            r"|pagamento\s+integral"
            r"|baixa\s+definitiva"
            r"|satisfa[çc][ãa]o\s+d[ao]\s+(cr[ée]dito|obriga[çc][ãa]o|d[ée]bito)"
            r"|encerramento\s+d[ao]\s+execu[çc][ãa]o"
            r"|obriga[çc][ãa]o\s+satisfeita",
            re.IGNORECASE,
        ),
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
