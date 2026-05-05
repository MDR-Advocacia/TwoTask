"""Mapeamento J.TR do CNJ → sigla de tribunal (compartilhado entre extractors)."""

from __future__ import annotations

from typing import Optional


# CNJ sem máscara: NNNNNNNDDAAAAJTROOOO (20 dígitos)
# Posição: 13 = J (segmento), 14-15 = TR (tribunal). Ver Resolução CNJ 65/2008.

# Justiça Estadual (J=8)
_TRIBUNAIS_ESTADUAIS = {
    "01": "TJAC", "02": "TJAL", "03": "TJAP", "04": "TJAM",
    "05": "TJBA", "06": "TJCE", "07": "TJDFT", "08": "TJES",
    "09": "TJGO", "10": "TJMA", "11": "TJMT", "12": "TJMS",
    "13": "TJMG", "14": "TJPA", "15": "TJPB", "16": "TJPR",
    "17": "TJPE", "18": "TJPI", "19": "TJRJ", "20": "TJRN",
    "21": "TJRS", "22": "TJRO", "23": "TJRR", "24": "TJSC",
    "25": "TJSE", "26": "TJSP", "27": "TJTO",
}

# Justiça Federal (J=4) — TRFs
_TRIBUNAIS_FEDERAIS = {
    "01": "TRF1", "02": "TRF2", "03": "TRF3",
    "04": "TRF4", "05": "TRF5", "06": "TRF6",
}

# Justiça do Trabalho (J=5) — TRTs
_TRIBUNAIS_TRABALHO = {
    f"{i:02d}": f"TRT{i}" for i in range(1, 25)
}


def tribunal_from_cnj(cnj: str) -> Optional[str]:
    """
    Deriva a sigla do tribunal a partir do CNJ.

    Aceita CNJ com ou sem máscara. Retorna None se não conseguir mapear
    (deixa pro motor de classificação preencher).
    """
    digits = "".join(c for c in cnj if c.isdigit())
    if len(digits) < 16:
        return None
    j = digits[13]
    tr = digits[14:16]
    if j == "8":
        return _TRIBUNAIS_ESTADUAIS.get(tr)
    if j == "4":
        return _TRIBUNAIS_FEDERAIS.get(tr)
    if j == "5":
        return _TRIBUNAIS_TRABALHO.get(tr)
    return None
