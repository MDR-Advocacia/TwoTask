"""Schema Pydantic do MODO AUDITORIA do Classificador.

Valida o JSON que a IA retorna no fluxo de auditoria forense externa
(banca terceirizada). NAO usar em producao do Classificador — esse
modulo e' incidental.

Schema espelhado do prompt em `audit_prompts.AUDIT_SYSTEM_PROMPT`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# ─── Enums (validados como str ja' que Pydantic lida bem com Literal) ─

CATEGORIAS_VALIDAS = {
    "FASE_INICIAL",
    "CONTESTACAO",
    "AUDIENCIA",
    "INSTRUCAO",
    "RECURSO",
    "CUMPRIMENTO",
    "GESTAO",
    "ADMINISTRATIVA",
}

SEVERIDADES_VALIDAS = {"CRITICA", "ALTA", "MEDIA", "BAIXA"}

PAPEIS_EMPRESA = {"principal", "secundaria"}

EVIDENCIA_TIPOS = {"polo_passivo_advogados", "header_peca_assinada", "ambos"}

CONFIANCAS = {"alta", "media", "baixa"}

# Codigos validos por prefixo — relaxado: aceita F1xx-F8xx e R9xx
CODIGO_FALHA_RE = re.compile(r"^F[1-8]\d{2}$")
CODIGO_RESULTADO_RE = re.compile(r"^R9\d{2}$")


# ─── Models ───────────────────────────────────────────────────────────


class EmpresaRepresentada(BaseModel):
    """Empresa do polo passivo que GIOVANNA representa neste processo."""

    model_config = ConfigDict(extra="ignore")

    nome: str
    cnpj: Optional[str] = None
    papel: str = Field(default="principal")
    evidencia_tipo: Optional[str] = None
    evidencia_citada: Optional[str] = None
    observacao: Optional[str] = None

    @field_validator("papel")
    @classmethod
    def _valida_papel(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in PAPEIS_EMPRESA:
            raise ValueError(f"papel inválido: {v!r} (use {PAPEIS_EMPRESA})")
        return v

    @field_validator("evidencia_tipo")
    @classmethod
    def _valida_evidencia_tipo(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in EVIDENCIA_TIPOS:
            # Toleramos — algumas vezes a IA usa termo aproximado
            logger.debug("evidencia_tipo nao reconhecida: %s", v)
            return v
        return v


class FalhaConfirmada(BaseModel):
    """Falha processual com evidencia direta (codigos F1xx-F8xx)."""

    model_config = ConfigDict(extra="ignore")

    codigo: str
    categoria: str
    severidade: str
    descricao_curta: str
    data_ocorrencia: Optional[str] = None
    empresa_afetada: Optional[str] = None
    evidencia_citada: str
    prejuizo_estimado: Optional[float] = None
    fundamentacao_auditor: Optional[str] = None

    @field_validator("codigo")
    @classmethod
    def _valida_codigo(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not CODIGO_FALHA_RE.match(v):
            raise ValueError(f"codigo de falha invalido: {v!r} (esperado F1xx-F8xx)")
        return v

    @field_validator("categoria")
    @classmethod
    def _valida_categoria(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"categoria invalida: {v!r}")
        return v

    @field_validator("severidade")
    @classmethod
    def _valida_severidade(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in SEVERIDADES_VALIDAS:
            raise ValueError(f"severidade invalida: {v!r}")
        return v


class IndicioFalha(BaseModel):
    """Sinal de falha sem evidencia direta suficiente — pra revisao manual.

    Em indicios, `severidade` e' opcional (default MEDIA) — a IA frequentemente
    omite quando o caso e' fraco demais pra cravar severidade. Falhas
    confirmadas continuam exigindo severidade obrigatoria.
    """

    model_config = ConfigDict(extra="ignore")

    codigo: str
    categoria: str
    severidade: Optional[str] = None
    descricao_curta: str
    data_ocorrencia: Optional[str] = None
    empresa_afetada: Optional[str] = None
    evidencia_citada: Optional[str] = None
    motivo_indicio: Optional[str] = None

    _valida_codigo = field_validator("codigo")(FalhaConfirmada._valida_codigo.__func__)
    _valida_categoria = field_validator("categoria")(FalhaConfirmada._valida_categoria.__func__)

    @field_validator("severidade")
    @classmethod
    def _valida_severidade_opcional(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        v = str(v).strip().upper()
        if v not in SEVERIDADES_VALIDAS:
            logger.debug("severidade de indicio invalida: %s — usando None", v)
            return None
        return v


class DadoInsuficiente(BaseModel):
    """Ponto que o auditor examinou mas faltou dado pra concluir."""

    model_config = ConfigDict(extra="ignore")

    ponto_examinado: str
    motivo: Optional[str] = None


class ResultadoNegativo(BaseModel):
    """Resultado processual desfavoravel (codigos R9xx) — separado de falha."""

    model_config = ConfigDict(extra="ignore")

    codigo: str
    descricao_curta: str
    data: Optional[str] = None
    empresa_afetada: Optional[str] = None
    valor_envolvido: Optional[float] = None
    evidencia_citada: Optional[str] = None
    falha_associada_codigo: Optional[str] = None

    @field_validator("codigo")
    @classmethod
    def _valida_codigo(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not CODIGO_RESULTADO_RE.match(v):
            raise ValueError(f"codigo de resultado invalido: {v!r} (esperado R9xx)")
        return v

    @field_validator("falha_associada_codigo")
    @classmethod
    def _valida_falha_assoc(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        v = v.strip().upper()
        if not CODIGO_FALHA_RE.match(v):
            logger.debug("falha_associada_codigo nao bate F1xx-F8xx: %s", v)
            return v  # toleramos
        return v


# ─── v2: diagnostico rico (flex da ferramenta) ────────────────────────


TIPOS_RESULTADO = {
    "procedente",
    "improcedente",
    "parcialmente_procedente",
    "extincao_sem_merito",
    "extincao_com_merito_outro",
    "acordo_homologado",
    "em_andamento",
}

EM_FAVOR_DE = {"autor", "reu_giovanna", "ambos_parcial"}

PROBABILIDADES_PERDA = {"remota", "possivel", "provavel"}

NATUREZAS_PEDIDO = {"CONSUMERISTA", "CIVIL", "TRABALHISTA", "TRIBUTARIO", "OUTRO"}


class ResultadoProcesso(BaseModel):
    """Resultado do processo (sentenca/decisao definitiva) — espelha
    bloco `sentenca` do Classificador atual.
    """

    model_config = ConfigDict(extra="ignore")

    existe: bool = False
    tipo: Optional[str] = None
    data: Optional[str] = None
    em_favor_de: Optional[str] = None
    valor_condenacao: Optional[float] = None
    resumo: Optional[str] = None
    evidencia_citada: Optional[str] = None

    @field_validator("tipo")
    @classmethod
    def _valida_tipo(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        v = str(v).strip().lower()
        if v not in TIPOS_RESULTADO:
            logger.debug("tipo de resultado nao reconhecido: %s — mantendo", v)
        return v

    @field_validator("em_favor_de")
    @classmethod
    def _valida_em_favor(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        v = str(v).strip().lower()
        if v not in EM_FAVOR_DE:
            logger.debug("em_favor_de nao reconhecido: %s — mantendo", v)
        return v


class AnaliseQuantitativa(BaseModel):
    """Agregado do processo — valor total em risco, PCOND, PE global."""

    model_config = ConfigDict(extra="ignore")

    valor_estimado_total: Optional[float] = None
    pcond_total: Optional[float] = None
    prob_exito_global: Optional[float] = None

    @field_validator("prob_exito_global")
    @classmethod
    def _valida_pe(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        # Clamp 0.0-1.0 — IA as vezes manda 0-100
        f = float(v)
        if f > 1.0 and f <= 100.0:
            f = f / 100.0
        return max(0.0, min(1.0, f))


class Pedido(BaseModel):
    """1 pedido do autor — com valores, prob_perda e CPC 25."""

    model_config = ConfigDict(extra="ignore")

    tipo_pedido: str
    natureza: Optional[str] = None
    valor_indicado: Optional[float] = None
    valor_estimado: Optional[float] = None
    fundamentacao_valor: Optional[str] = None
    probabilidade_perda: Optional[str] = None
    aprovisionamento: Optional[float] = None
    fundamentacao_risco: Optional[str] = None

    @field_validator("natureza")
    @classmethod
    def _valida_natureza(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        v = str(v).strip().upper()
        if v not in NATUREZAS_PEDIDO:
            logger.debug("natureza de pedido nao reconhecida: %s — mantendo", v)
        return v

    @field_validator("probabilidade_perda")
    @classmethod
    def _valida_prob(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        v = str(v).strip().lower()
        if v not in PROBABILIDADES_PERDA:
            logger.debug("probabilidade_perda nao reconhecida: %s — mantendo", v)
        return v


class AuditResponse(BaseModel):
    """Response completo do auditor pra 1 processo (v2 — com diagnostico rico)."""

    model_config = ConfigDict(extra="ignore")

    cnj_number: Optional[str] = None
    tribunal: Optional[str] = None
    vara: Optional[str] = None
    fase_processual: Optional[str] = None
    valor_causa: Optional[float] = None
    categoria_processo: Optional[str] = None

    empresas_representadas: list[EmpresaRepresentada] = Field(default_factory=list)
    falhas_confirmadas: list[FalhaConfirmada] = Field(default_factory=list)
    indicios_de_falha: list[IndicioFalha] = Field(default_factory=list)
    dados_insuficientes: list[DadoInsuficiente] = Field(default_factory=list)
    resultados_negativos: list[ResultadoNegativo] = Field(default_factory=list)

    # v2: diagnostico rico
    resultado_processo: Optional[ResultadoProcesso] = None
    analise_quantitativa: Optional[AnaliseQuantitativa] = None
    pedidos: list[Pedido] = Field(default_factory=list)

    resumo_executivo: Optional[str] = None
    observacoes_auditor: Optional[str] = None
    confianca_geral: str = "media"

    @field_validator("confianca_geral")
    @classmethod
    def _valida_confianca(cls, v: str) -> str:
        v = (v or "media").strip().lower()
        if v not in CONFIANCAS:
            logger.debug("confianca_geral fora de %s: %s", CONFIANCAS, v)
            return "media"
        return v


# ─── Parser ───────────────────────────────────────────────────────────


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _strip_code_fences(text: str) -> str:
    """Remove ```json...``` se a IA descumpriu o contrato e devolveu fenced."""
    if not text:
        return text
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_first_json_object(text: str) -> Optional[str]:
    """Acha o primeiro objeto JSON balanceado no texto.

    Se a IA mandou texto antes/depois, isso pesca o objeto bruto.
    """
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class AuditParseError(Exception):
    """Erro ao parsear response da IA — preserva trecho original."""

    def __init__(self, message: str, raw_text: str = ""):
        super().__init__(message)
        self.raw_text = raw_text


def parse_audit_response(raw_text: str) -> AuditResponse:
    """Parseia a string da IA → AuditResponse Pydantic.

    Tolera: code fences, texto antes/depois, objeto json balanceado
    no meio. Levanta AuditParseError com trecho original se falhar.
    """
    if not raw_text or not raw_text.strip():
        raise AuditParseError("Response vazia da IA.", raw_text)

    candidate = _strip_code_fences(raw_text)

    # 1) Tenta parsear direto
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # 2) Extrai primeiro objeto JSON balanceado
        extracted = _extract_first_json_object(candidate)
        if not extracted:
            raise AuditParseError(
                "Nao encontrei objeto JSON na resposta da IA.",
                raw_text[:1000],
            )
        try:
            data = json.loads(extracted)
        except json.JSONDecodeError as exc:
            raise AuditParseError(
                f"JSON invalido apos extracao: {exc}",
                raw_text[:1000],
            ) from exc

    if not isinstance(data, dict):
        raise AuditParseError(
            f"Esperado objeto JSON na raiz, recebido {type(data).__name__}.",
            raw_text[:1000],
        )

    # 3) Validacao Pydantic — pode levantar ValidationError; aqui
    # deixamos propagar pra o caller decidir se descarta o processo
    # ou move pra retry/dados_insuficientes.
    return AuditResponse.model_validate(data)
