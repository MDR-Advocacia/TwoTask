"""Lookup tables AJUS — display string ↔ código numérico.

Capturados via dump dos stores Ext do form principal de edição da
capa em 07/05/2026 (process 99580). Esses códigos sao os que vao
no payload do POST /ajax.handler.php?id=numberid.41 (action=update).

Estratégia de uso: o RPA conhece os displays (vem da planilha em
texto: "Consumidor", "Justiça Comum", "Remoto", "Cível"). Antes de
fazer o POST direto, traduz pra cod via essas tabelas.

Comportamento em chave desconhecida: ValueError. Nao falhar silente
gravando codigo errado no AJUS.
"""

from __future__ import annotations


# ── codClassificacaoAcaoJudicial (Materia) ─────────────────────────────
# Store completo do combo (7 itens):
MATTER_CODE: dict[str, int] = {
    "Administrativo": 7,
    "Cível": 2,
    "Consumidor": 3,
    "Criminal": 5,
    "Não Classif.": 1,
    "Trabalhista": 6,
    "Tributário": 4,
}


# ── codTipoResultadoFinal (Justica/Honorario) ──────────────────────────
# Store completo do combo (3 itens):
JUSTICE_FEE_CODE: dict[str, int] = {
    "Juizado Especial Cível": 3,
    "Justiça Comum": 2,
    "Não Definido": 1,
}


# ── codProbabilidadePerda (Risco) ──────────────────────────────────────
# Store completo do combo (4 itens):
RISK_CODE: dict[str, int] = {
    "Possível": 2,
    "Praticamente Certo": 4,
    "Provável": 3,
    "Remoto": 1,
}


# ── codNatureza ────────────────────────────────────────────────────────
# Store completo tem ~700 itens. RPA hoje usa "Cível" hardcoded pra
# Consumidor. Outros valores sao adicionados conforme demanda.
NATUREZA_CODE: dict[str, int] = {
    "Cível": 69,
}


def _norm(name: str | None) -> str:
    """Normaliza display antes do lookup — strip + colapsa espaços."""
    if not name:
        return ""
    return " ".join(str(name).strip().split())


def matter_to_code(name: str | None) -> int:
    norm = _norm(name)
    try:
        return MATTER_CODE[norm]
    except KeyError as exc:
        raise ValueError(
            f"Matéria desconhecida: {name!r}. "
            f"Opções: {sorted(MATTER_CODE)}"
        ) from exc


def justice_fee_to_code(name: str | None) -> int:
    norm = _norm(name)
    try:
        return JUSTICE_FEE_CODE[norm]
    except KeyError as exc:
        raise ValueError(
            f"Justiça/Honorário desconhecido: {name!r}. "
            f"Opções: {sorted(JUSTICE_FEE_CODE)}"
        ) from exc


def risk_to_code(name: str | None) -> int:
    norm = _norm(name)
    try:
        return RISK_CODE[norm]
    except KeyError as exc:
        raise ValueError(
            f"Risco/Prob. Perda desconhecido: {name!r}. "
            f"Opções: {sorted(RISK_CODE)}"
        ) from exc


def natureza_to_code(name: str = "Cível") -> int:
    norm = _norm(name)
    try:
        return NATUREZA_CODE[norm]
    except KeyError as exc:
        raise ValueError(
            f"Natureza desconhecida: {name!r}. "
            f"Opções: {sorted(NATUREZA_CODE)}"
        ) from exc
