"""
Schema Pydantic para validar a resposta JSON do classificador de
publicações e capturar inconsistências semânticas que `repair_classification`
e `validate_classification` não pegam (eles cuidam só do par
categoria/subcategoria contra a taxonomia).

O que ESTE módulo valida:
  - Cross-field: `audiencia_data`/`audiencia_hora`/`audiencia_link` só
    podem vir preenchidos quando `categoria == "Audiência Agendada"`.
  - `prazo_dias` exige `prazo_tipo` e `prazo_fundamentacao` preenchidos.
  - `prazo_dias` ausente exige `prazo_tipo` e `prazo_fundamentacao` null.
  - `confianca` ∈ {alta, media, baixa}.
  - `polo` ∈ {ativo, passivo, ambos}.
  - Datas em ISO `YYYY-MM-DD` e horas em `HH:MM`.

Quando inconsistente: o validador NÃO levanta — limpa os campos
incoerentes (ex.: zera `audiencia_data` se categoria não é "Audiência
Agendada"), e devolve uma lista de `warnings` que o caller pode logar.
Esse modo "permissivo" foi escolhido porque queremos APROVEITAR a
classificação principal (categoria/subcategoria) mesmo quando a IA
alucinou um campo extra — só sanitizamos o lixo antes de gravar.

Quando o erro é estrutural (categoria ausente, payload não-dict),
levanta `ResponseSchemaError`.

Uso típico no orquestrador:

    from app.services.classifier.response_schema import (
        validate_response,
        ResponseSchemaError,
    )

    try:
        clean = validate_response(result)
    except ResponseSchemaError as exc:
        # marca pra revisão humana; não persiste classificação
        ...
    else:
        if clean.warnings:
            logger.warning("Schema warnings #%s: %s", rec.id, clean.warnings)
        rec.category = clean.categoria
        rec.subcategory = clean.subcategoria
        # ... (campos limpos pelo validator, sem alucinações cruzadas)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


class ResponseSchemaError(ValueError):
    """Erro estrutural na resposta — não dá pra aproveitar nem a categoria."""


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_VALID_POLOS = {"ativo", "passivo", "ambos"}
_VALID_CONFIANCA = {"alta", "media", "baixa"}
_VALID_PRAZO_TIPO = {"util", "corrido"}
_AUDIENCIA_CATEGORY = "Audiência Agendada"


@dataclass
class CleanClassification:
    """Resultado validado e sanitizado pronto pra persistir."""

    categoria: str
    subcategoria: str
    polo: Optional[str]
    audiencia_data: Optional[str]
    audiencia_hora: Optional[str]
    audiencia_link: Optional[str]
    prazo_dias: Optional[int]
    prazo_tipo: Optional[str]
    prazo_fundamentacao: Optional[str]
    confianca: Optional[str]
    justificativa: str
    natureza_processo: Optional[str]
    warnings: list[str] = field(default_factory=list)


def _coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return str(value).strip() or None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        # bool é subclass de int em Python; trata como int normal seria
        # surpresa pra IA que retorna `false` ao invés de null.
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_response(payload: Any) -> CleanClassification:
    """
    Valida e sanitiza a resposta da IA. Devolve CleanClassification.

    Levanta ResponseSchemaError em casos irrecuperáveis:
      - payload não é dict
      - sem `categoria` (mesmo após coerção)

    Caso contrário, qualquer inconsistência cross-field vira warning e
    o campo problemático é zerado (ex.: audiencia_data limpa se
    categoria != "Audiência Agendada").
    """
    if not isinstance(payload, dict):
        raise ResponseSchemaError(
            f"payload não é objeto JSON ({type(payload).__name__})"
        )

    warnings: list[str] = []

    categoria = _coerce_str(payload.get("categoria"))
    if not categoria:
        raise ResponseSchemaError("campo 'categoria' ausente ou vazio")

    subcategoria = _coerce_str(payload.get("subcategoria")) or "-"
    polo_raw = (_coerce_str(payload.get("polo")) or "").lower()
    polo: Optional[str]
    if polo_raw in _VALID_POLOS:
        polo = polo_raw
    else:
        if polo_raw:
            warnings.append(f"polo inválido '{polo_raw}' — descartado")
        polo = None

    audiencia_data = _coerce_str(payload.get("audiencia_data"))
    audiencia_hora = _coerce_str(payload.get("audiencia_hora"))
    audiencia_link = _coerce_str(payload.get("audiencia_link"))

    # Cross-field: campos de audiência só fazem sentido na categoria certa.
    is_audiencia = categoria == _AUDIENCIA_CATEGORY
    if not is_audiencia:
        if audiencia_data:
            warnings.append(
                f"audiencia_data='{audiencia_data}' descartada (categoria='{categoria}' não é '{_AUDIENCIA_CATEGORY}')"
            )
            audiencia_data = None
        if audiencia_hora:
            warnings.append(
                f"audiencia_hora='{audiencia_hora}' descartada (categoria != '{_AUDIENCIA_CATEGORY}')"
            )
            audiencia_hora = None
        if audiencia_link:
            warnings.append(
                f"audiencia_link descartado (categoria != '{_AUDIENCIA_CATEGORY}')"
            )
            audiencia_link = None

    # Formato de data/hora — só aceita ISO; senão zera com warning.
    if audiencia_data and not _DATE_RE.match(audiencia_data):
        warnings.append(
            f"audiencia_data='{audiencia_data}' fora do padrão YYYY-MM-DD — zerada"
        )
        audiencia_data = None
    if audiencia_hora and not _TIME_RE.match(audiencia_hora):
        warnings.append(
            f"audiencia_hora='{audiencia_hora}' fora do padrão HH:MM — zerada"
        )
        audiencia_hora = None

    # Prazo — trio audiência atrelado.
    prazo_dias = _coerce_int(payload.get("prazo_dias"))
    prazo_tipo = (_coerce_str(payload.get("prazo_tipo")) or "").lower() or None
    prazo_fundamentacao = _coerce_str(payload.get("prazo_fundamentacao"))

    if prazo_dias is not None:
        if prazo_dias <= 0 or prazo_dias > 365:
            warnings.append(
                f"prazo_dias={prazo_dias} fora do range 1..365 — zerado todo o trio"
            )
            prazo_dias = None
            prazo_tipo = None
            prazo_fundamentacao = None
        else:
            if prazo_tipo not in _VALID_PRAZO_TIPO:
                if prazo_tipo:
                    warnings.append(
                        f"prazo_tipo='{prazo_tipo}' inválido — assumindo 'util'"
                    )
                else:
                    warnings.append(
                        "prazo_tipo ausente com prazo_dias preenchido — assumindo 'util'"
                    )
                prazo_tipo = "util"
            if not prazo_fundamentacao:
                warnings.append(
                    "prazo_fundamentacao ausente com prazo_dias preenchido — operador deverá completar"
                )
    else:
        if prazo_tipo:
            warnings.append(
                f"prazo_tipo='{prazo_tipo}' descartado (prazo_dias é null)"
            )
            prazo_tipo = None
        if prazo_fundamentacao:
            warnings.append(
                "prazo_fundamentacao descartada (prazo_dias é null)"
            )
            prazo_fundamentacao = None

    confianca = (_coerce_str(payload.get("confianca")) or "").lower() or None
    if confianca and confianca not in _VALID_CONFIANCA:
        warnings.append(
            f"confianca='{confianca}' inválida — assumindo 'baixa'"
        )
        confianca = "baixa"

    justificativa = _coerce_str(payload.get("justificativa")) or ""

    natureza_processo = _coerce_str(payload.get("natureza_processo"))

    return CleanClassification(
        categoria=categoria,
        subcategoria=subcategoria,
        polo=polo,
        audiencia_data=audiencia_data,
        audiencia_hora=audiencia_hora,
        audiencia_link=audiencia_link,
        prazo_dias=prazo_dias,
        prazo_tipo=prazo_tipo,
        prazo_fundamentacao=prazo_fundamentacao,
        confianca=confianca,
        justificativa=justificativa,
        natureza_processo=natureza_processo,
        warnings=warnings,
    )
