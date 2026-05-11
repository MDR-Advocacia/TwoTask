"""Diff hash e calculo de changed_fields entre snapshots normalizados.

A lista SIGNIFICANT_FIELDS foi curada deliberadamente:
- INCLUI campos que indicam mudanca real (situacao, valores, andamento, partes).
- EXCLUI campos volateis que mudam a cada export sem significado
  (dias_ult_atualizacao, data_ult_andamento, data_cadastro_acao,
  usuario_cadastro_acao). Isso evita ATUALIZADO ruido — operador so
  ve mudancas que importam.

A normalizacao via _hashable evita falso-positivo entre Decimal('1500.00')
e str '1500.00' (que e' como o payload e' serializado pra JSONB no DB).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


SIGNIFICANT_FIELDS: tuple[str, ...] = (
    "situacao_processo",
    "polo",
    "materia",
    "risco_prob_perda",
    "tipo_acao",
    "natureza",
    "numero_vara",
    "foro",
    "comarca",
    "uf",
    "grupo_responsavel",
    "usuario_responsavel",
    "escritorio_responsavel",
    "valor_causa",
    "valor_prev_acordo",
    "valor_acordo",
    "valor_discutido",
    "valor_exito",
    "valor_condenacao",
    "valor_contingencia",
    "ult_andamento",
    "autores_json",
    "reus_json",
    "numero_processo",
    "numero_pasta",
    "numero_interno",
    "numero_contrato",
    "acao_principal",
    "processo_virtual",
    "justica_honorario",
    "distribuido_em",
)


def _hashable(v: Any) -> Any:
    """Normaliza tipos pra comparacao estavel.

    Decimals -> string, datetimes/dates -> isoformat (str), bool/int/str/None mantidos,
    listas/dicts mantidos (sort_keys do json garante ordem estavel depois).
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return [_hashable(x) for x in v]
    if isinstance(v, dict):
        return {k: _hashable(val) for k, val in v.items()}
    # Decimal, datetime, date — converte pra string
    return str(v)


def compute_diff_hash(normalized: dict) -> str:
    """sha256 dos campos significativos do payload normalizado.

    Estavel via sort_keys e _hashable. Reupload do mesmo processo gera o
    mesmo hash.
    """
    payload = {k: _hashable(normalized.get(k)) for k in SIGNIFICANT_FIELDS}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


def compute_changed_fields(before: dict, after: dict) -> dict:
    """Retorna {campo: {"de": x, "para": y}} pra campos significativos que mudaram.

    Compara via _hashable pra evitar falso-positivo entre tipos serializados
    diferentes do mesmo valor logico.
    """
    diffs: dict[str, dict] = {}
    for k in SIGNIFICANT_FIELDS:
        b = _hashable(before.get(k))
        a = _hashable(after.get(k))
        if b != a:
            diffs[k] = {"de": before.get(k), "para": after.get(k)}
    return diffs
