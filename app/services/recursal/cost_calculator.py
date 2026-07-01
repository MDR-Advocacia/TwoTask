"""
Cálculo DETERMINÍSTICO do custo de preparo recursal.

A IA não chuta custas. O custo é calculado por lookup na tabela
`recursal_custas` (alimentada pelo operador):

    preparo = clamp(valor_causa * percentual% + valor_fixo,
                    valor_minimo, valor_maximo) + porte_remessa_retorno

Enquanto a tabela estiver vazia (planilha ainda não cadastrada), o custo
fica `None` e o motivo é registrado no detalhe — a análise de mérito não
depende disso.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.analise_recursal import RecursalCustaTabela


# Tribunais da Justiça Estadual (segmento J=8): código TR → UF.
# Determinístico e padronizado pelo CNJ (Res. CNJ 65/2008).
_TJ_TR_TO_UF = {
    "01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA",
    "06": "CE", "07": "DF", "08": "ES", "09": "GO", "10": "MA",
    "11": "MT", "12": "MS", "13": "MG", "14": "PA", "15": "PB",
    "16": "PR", "17": "PE", "18": "PI", "19": "RJ", "20": "RN",
    "21": "RS", "22": "RO", "23": "RR", "24": "SC", "25": "SE",
    "26": "SP", "27": "TO",
}


def derive_uf_from_cnj(cnj: Optional[str]) -> Optional[str]:
    """
    Deriva a UF a partir do CNJ, quando for Justiça Estadual (J=8).

    CNJ = NNNNNNN-DD.AAAA.J.TR.OOOO (20 dígitos). J = dígito 14 (índice 13),
    TR = dígitos 15-16 (índices 14-15). Para J=8, TR mapeia direto pra UF.
    Retorna None para outros segmentos (federal, trabalho, etc.) ou CNJ
    malformado — nesses casos o operador define a UF manualmente.
    """
    if not cnj:
        return None
    digits = re.sub(r"\D", "", str(cnj))
    if len(digits) != 20:
        return None
    segmento = digits[13]
    tribunal = digits[14:16]
    if segmento != "8":  # só Justiça Estadual mapeia TR→UF de forma direta
        return None
    return _TJ_TR_TO_UF.get(tribunal)


def calcular_custo(
    db: Session,
    *,
    uf: Optional[str],
    tipo_recurso: Optional[str],
    valor_causa: Optional[float],
) -> Tuple[Optional[float], dict]:
    """
    Calcula o custo de preparo. Retorna (custo, detalhe).

    `custo` é None (com motivo no `detalhe`) quando faltar UF, tipo de
    recurso, valor da causa, ou quando não houver linha de custas
    cadastrada para o par (UF, tipo_recurso).
    """
    if not uf:
        return None, {"motivo": "sem_uf"}
    if not tipo_recurso:
        return None, {"motivo": "sem_tipo_recurso"}
    if valor_causa is None:
        return None, {"motivo": "sem_valor_causa", "uf": uf, "tipo_recurso": tipo_recurso}

    row = (
        db.query(RecursalCustaTabela)
        .filter(RecursalCustaTabela.uf == uf)
        .filter(RecursalCustaTabela.tipo_recurso == tipo_recurso)
        .filter(RecursalCustaTabela.ativo.is_(True))
        .order_by(RecursalCustaTabela.vigencia.desc().nullslast())
        .first()
    )
    if row is None:
        return None, {
            "motivo": "sem_tabela_de_custas",
            "uf": uf,
            "tipo_recurso": tipo_recurso,
        }

    pct = float(row.percentual or 0)
    fixo = float(row.valor_fixo or 0)
    minimo = float(row.valor_minimo) if row.valor_minimo is not None else None
    maximo = float(row.valor_maximo) if row.valor_maximo is not None else None
    porte = float(row.porte_remessa_retorno or 0)

    variavel = float(valor_causa) * pct / 100.0
    base = fixo + variavel
    base_clamped = base
    if minimo is not None and base_clamped < minimo:
        base_clamped = minimo
    if maximo is not None and base_clamped > maximo:
        base_clamped = maximo
    total = round(base_clamped + porte, 2)

    detalhe = {
        "uf": uf,
        "tribunal": row.tribunal,
        "tipo_recurso": tipo_recurso,
        "valor_causa": float(valor_causa),
        "percentual": pct,
        "valor_fixo": fixo,
        "valor_minimo": minimo,
        "valor_maximo": maximo,
        "porte_remessa_retorno": porte,
        "componente_variavel": round(variavel, 2),
        "subtotal_antes_clamp": round(base, 2),
        "subtotal_apos_clamp": round(base_clamped, 2),
        "vigencia": row.vigencia,
        "fundamentacao": row.fundamentacao,
        "total": total,
    }
    return total, detalhe
