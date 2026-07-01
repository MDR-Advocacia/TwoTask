"""
Schema Pydantic (V2) do veredito de viabilidade recursal.

A IA (Sonnet) devolve este JSON. `custo_estimado` NÃO está aqui — o custo
do preparo é calculado de forma determinística (lookup em `recursal_custas`)
a partir de `valor_causa` + `tipo_recurso` + UF; a IA não chuta custas.

Os validadores são TOLERANTES de propósito: normalizam caixa/acentos e,
diante de um valor fora do domínio, caem em `None` (em vez de quebrar o
parse do batch inteiro). O operador revê no card.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

# ─── Domínios ─────────────────────────────────────────────────────────
RESULTADO_DECISAO_VALIDOS = {"PROCEDENTE", "IMPROCEDENTE", "PARCIAL", "EXTINTO"}
TIPO_DECISAO_VALIDOS = {"SENTENCA", "ACORDAO", "DECISAO_INTERLOCUTORIA"}
PROBABILIDADE_REVERSAO_VALIDOS = {"REMOTA", "POSSIVEL", "PROVAVEL"}
RECORRER_VALIDOS = {"SIM", "NAO", "LIMITROFE"}
# Recursos cíveis relevantes pro Master. NÃO recomendamos embargos de
# declaração (fora da lista). Recurso inominado = recurso da sentença nos
# Juizados Especiais (JEC); apelação = Vara Cível comum.
TIPO_RECURSO_VALIDOS = {"APELACAO", "RECURSO_INOMINADO", "AGRAVO", "RESP", "RE"}
CONFIANCA_VALIDOS = {"ALTA", "MEDIA", "BAIXA"}


def _normalize(value: Optional[str]) -> Optional[str]:
    """UPPER + sem acento + troca espaço/hífen por underscore. None-safe."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    txt = value.strip()
    if not txt:
        return None
    # Remove acentos.
    txt = "".join(
        c for c in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(c)
    )
    return txt.upper().replace(" ", "_").replace("-", "_")


def _coerce(value: Optional[str], dominio: set[str]) -> Optional[str]:
    norm = _normalize(value)
    return norm if norm in dominio else None


class RecursalVerdict(BaseModel):
    """Veredito de viabilidade recursal de um único processo."""

    model_config = {"extra": "ignore"}

    # Identificação (cabeçalho/assunto do parecer).
    nome_autor: Optional[str] = None
    cpf: Optional[str] = None
    objeto: Optional[str] = None          # ex.: "Negativa de Contratação"
    produto: Optional[str] = None         # ex.: "Credcesta"

    # Resultado da decisão sob a ótica do Banco Master (réu).
    resultado_decisao: Optional[str] = None
    tipo_decisao: Optional[str] = None
    # Resumo da decisão: tópicos das determinações + destaque.
    resumo_topicos: List[str] = Field(default_factory=list)
    destaque: Optional[str] = None
    # Síntese da fundamentação do juízo.
    fundamentacao_juiz: Optional[str] = None
    # CRÍTICO: a contestação foi juntada COM documentos anexados? (só presença,
    # não qualidade). Documentos anexados = ponto POSITIVO para o banco.
    contestacao_com_documentos: Optional[bool] = None
    # Bullets da análise técnica ("observa-se que ...").
    pontos_analise: List[str] = Field(default_factory=list)
    # Chance de REVERTER a decisão desfavorável no recurso (puro mérito).
    probabilidade_reversao: Optional[str] = None
    # Recomendação final (mérito + custo).
    recorrer: Optional[str] = None
    tipo_recurso: Optional[str] = None
    # Justificativa objetiva da conclusão.
    fundamentacao: Optional[str] = None
    # Alimenta o cálculo determinístico de custo (a IA só extrai o número).
    valor_causa: Optional[float] = None
    # Valor da condenação — texto livre (número ou "Ilíquido").
    valor_condenacao: Optional[str] = None
    # Data em que o RÉU foi intimado / a decisão foi publicada (DJe). O código
    # calcula o prazo fatal = +N dias úteis a partir daqui (determinístico).
    data_intimacao: Optional[date] = None
    # Prazo fatal — só como FALLBACK se a IA achar a data pronta na íntegra;
    # o normal é o código computar a partir de data_intimacao.
    prazo_fatal: Optional[date] = None
    confianca: Optional[str] = None

    # ── Validadores de domínio (tolerantes) ──────────────────────────
    @field_validator("resultado_decisao", mode="before")
    @classmethod
    def _v_resultado(cls, v):
        return _coerce(v, RESULTADO_DECISAO_VALIDOS)

    @field_validator("tipo_decisao", mode="before")
    @classmethod
    def _v_tipo_decisao(cls, v):
        return _coerce(v, TIPO_DECISAO_VALIDOS)

    @field_validator("probabilidade_reversao", mode="before")
    @classmethod
    def _v_prob(cls, v):
        return _coerce(v, PROBABILIDADE_REVERSAO_VALIDOS)

    @field_validator("recorrer", mode="before")
    @classmethod
    def _v_recorrer(cls, v):
        return _coerce(v, RECORRER_VALIDOS)

    @field_validator("tipo_recurso", mode="before")
    @classmethod
    def _v_tipo_recurso(cls, v):
        return _coerce(v, TIPO_RECURSO_VALIDOS)

    @field_validator("confianca", mode="before")
    @classmethod
    def _v_confianca(cls, v):
        return _coerce(v, CONFIANCA_VALIDOS)

    @field_validator("pontos_analise", "resumo_topicos", mode="before")
    @classmethod
    def _v_lista(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, (list, tuple)):
            return []
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("contestacao_com_documentos", mode="before")
    @classmethod
    def _v_bool(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return v
        s = _normalize(v)
        if s in {"SIM", "TRUE", "1", "S", "VERDADEIRO"}:
            return True
        if s in {"NAO", "FALSE", "0", "N", "FALSO"}:
            return False
        return None

    @field_validator("prazo_fatal", "data_intimacao", mode="before")
    @classmethod
    def _v_prazo(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, date):
            return v
        s = str(v).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    @field_validator("valor_causa", mode="before")
    @classmethod
    def _v_valor(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, (int, float)):
            return float(v)
        # Aceita "12.345,67" / "R$ 12.345,67" / "12345.67".
        txt = str(v).strip()
        txt = txt.replace("R$", "").replace(" ", "")
        if "," in txt and "." in txt:
            # formato pt-BR: ponto = milhar, vírgula = decimal
            txt = txt.replace(".", "").replace(",", ".")
        elif "," in txt:
            txt = txt.replace(",", ".")
        try:
            return float(txt)
        except (TypeError, ValueError):
            return None
