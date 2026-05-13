"""Schema Pydantic da resposta da IA no fluxo Classificador.

A IA (Claude Sonnet) recebe capa+integra de um processo (vindo da
extracao mecanica do PI) e responde 1 objeto JSON com diagnostico de
carteira — NAO classificacao de prazos (isso e' o PI).

Diferencas em relacao ao schema do PI:
- SEM blocos de prazo (contestar/liminar/audiencia/julgamento/contrarrazoes)
- Adiciona: sentenca (resultado), transito_julgado, primeira_habilitacao_master
- Adiciona: categoria + subcategoria da taxonomy v2 (texto, IDs sao
  resolvidos mecanicamente pelo runner)
- Mantem: pedidos, analise_estrategica, patrocinio, contestacao_existente

Polimento do prompt vem na Fase 5 — esse schema e' o contrato estavel.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Tipos e constantes reusadas do PI ────────────────────────────────
# (importadas localmente nas funcoes que precisam pra evitar import
# circular — schema PI tem outras dependencias)

PoloMdr = Literal["autor", "reu", "ambos"]
NaturezaProcesso = Literal["COMUM", "JUIZADO", "AGRAVO_INSTRUMENTO", "OUTRO"]
ProbabilidadePerda = Literal["remota", "possivel", "provavel"]
Confianca = Literal["alta", "media", "baixa"]


# ─── Pedidos (espelho enxuto do PI) ───────────────────────────────────


class PedidoResponse(BaseModel):
    """Um pedido do autor extraido da PI."""

    tipo_pedido: str = Field(..., description="Codigo da tabela de tipos (DANOS_MORAIS, etc.)")
    natureza: Optional[str] = None
    valor_indicado: Optional[Decimal] = Field(default=None, ge=0)
    valor_estimado: Optional[Decimal] = Field(default=None, ge=0)
    fundamentacao_valor: Optional[str] = None
    probabilidade_perda: Optional[ProbabilidadePerda] = None
    aprovisionamento: Optional[Decimal] = Field(default=None, ge=0)
    fundamentacao_risco: Optional[str] = None


# ─── Patrocinio (espelho do PI, mantem regras MDR/Master) ─────────────


PatrocinioDecisao = Literal["MDR_ADVOCACIA", "OUTRO_ESCRITORIO", "CONDUCAO_INTERNA"]
NaturezaAcao = Literal[
    "CONSUMERISTA", "CIVIL_PUBLICA", "INQUERITO_ADMINISTRATIVO", "TRABALHISTA", "OUTRO",
]


class PatrocinioResponse(BaseModel):
    """Quem patrocina o caso. Espelho do bloco patrocinio do PI (pin018)."""

    aplicavel: bool = False
    decisao: Optional[PatrocinioDecisao] = None
    outro_escritorio_nome: Optional[str] = None
    outro_advogado_nome: Optional[str] = None
    outro_advogado_oab: Optional[str] = None
    outro_advogado_data_habilitacao: Optional[date] = None
    suspeita_devolucao: bool = False
    motivo_suspeita: Optional[str] = None
    natureza_acao: Optional[NaturezaAcao] = None
    polo_passivo_confirmado: bool = True
    polo_passivo_observacao: Optional[str] = None
    confianca: Optional[Confianca] = None
    fundamentacao: Optional[str] = None


# ─── Contestacao existente (espelho do PI, pin021) ────────────────────


class ContestacaoExistenteResponse(BaseModel):
    """Detecta contestacao ja apresentada no processo."""

    existe: bool = False
    apresentada_por_mdr: Optional[bool] = None
    apresentada_por_nome: Optional[str] = None
    apresentada_por_oab: Optional[str] = None
    parte_representada: Optional[str] = None
    data_apresentacao: Optional[date] = None
    generica: Optional[bool] = None
    analise_qualidade: Optional[str] = None
    justificativa: str = ""


# ─── Sentenca (NOVO — pedido pelo operador) ───────────────────────────


SentencaTipo = Literal[
    "procedente",
    "improcedente",
    "parcialmente_procedente",
    "extincao_sem_merito",
    "extincao_com_merito_outro",
]


class SentencaResponse(BaseModel):
    """Resultado de sentenca/decisao que poe fim ao processo."""

    existe: bool = False
    data: Optional[date] = None
    tipo: Optional[SentencaTipo] = None
    resumo: Optional[str] = Field(default=None, description="1-3 frases do dispositivo")
    # Valor da condenacao do MDR — preencher quando procedente/parcial
    valor_condenacao: Optional[Decimal] = Field(default=None, ge=0)
    fundamentacao: Optional[str] = None


# ─── Transito em julgado (NOVO) ──────────────────────────────────────


class TransitoJulgadoResponse(BaseModel):
    """Transito em julgado da sentenca/acordao."""

    transitado: bool = False
    data: Optional[date] = None
    fundamentacao: Optional[str] = Field(
        default=None,
        description="Trecho/movimentacao que comprova (certidao de transito, etc.)",
    )


# ─── Primeira habilitacao Master (NOVO) ───────────────────────────────


class PrimeiraHabilitacaoMasterResponse(BaseModel):
    """Qual advogado se habilitou PRIMEIRO em nome de uma vinculada Master.

    Diferente de `patrocinio.outro_advogado_*`: aquele e' o advogado
    APONTADO pela IA como "suspeita de devolucao". Este aqui e' o
    PRIMEIRO HISTORICAMENTE — pode ou nao coincidir.
    """

    existe: bool = False
    advogado_nome: Optional[str] = None
    advogado_oab: Optional[str] = None
    escritorio_nome: Optional[str] = None
    data_habilitacao: Optional[date] = None
    parte_representada: Optional[str] = Field(
        default=None, description="Qual vinculada Master (Banco Master S/A, etc.)"
    )


# ─── Resposta principal ───────────────────────────────────────────────


class ClassificadorClassificationResponse(BaseModel):
    """Resposta integral da IA pra classificacao do processo no Classificador.

    Schema independente do PI — focado em DIAGNOSTICO DE CARTEIRA.
    """

    # ─── Classificacao taxonomy v2 (texto, ID resolve mecanicamente) ──
    # IA preenche o NOME da categoria/sub conforme apresentado na user
    # message. Runner cruza com classification_categories/subcategories
    # pra resolver os IDs.
    categoria_nome: Optional[str] = Field(
        default=None,
        description="Nome da categoria da taxonomy v2 (literal, conforme user message)",
    )
    subcategoria_nome: Optional[str] = Field(default=None)
    polo: Optional[PoloMdr] = None
    natureza_processo: Optional[NaturezaProcesso] = None
    produto: Optional[str] = None

    # ─── Valores e provisao agregados do processo ────────────────────
    valor_estimado_total: Optional[Decimal] = Field(default=None, ge=0)
    pcond_total: Optional[Decimal] = Field(default=None, ge=0)
    # Probabilidade de exito GLOBAL do MDR (0.0 = perde tudo, 1.0 = ganha tudo)
    prob_exito_global: Optional[Decimal] = Field(default=None, ge=0, le=1)

    # ─── Pedidos do autor ────────────────────────────────────────────
    pedidos: list[PedidoResponse] = Field(default_factory=list)

    # ─── Analise estrategica + observacoes ───────────────────────────
    analise_estrategica: Optional[str] = Field(
        default=None,
        description="2-3 frases sobre o caso, prob. exito MDR, aprovisionamento",
    )
    observacoes: Optional[str] = Field(
        default=None,
        description="Alerta critico pro operador HITL (truncamento, ambiguidade, etc.)",
    )

    # ─── Blocos paralelos (espelhos do PI) ───────────────────────────
    patrocinio: Optional[PatrocinioResponse] = None
    contestacao_existente: Optional[ContestacaoExistenteResponse] = None

    # ─── NOVOS (pedidos pelo operador 2026-05-13) ────────────────────
    sentenca: Optional[SentencaResponse] = None
    transito_julgado: Optional[TransitoJulgadoResponse] = None
    primeira_habilitacao_master: Optional[PrimeiraHabilitacaoMasterResponse] = None

    # ─── Confianca global ────────────────────────────────────────────
    confianca_geral: Confianca = "alta"

    @field_validator("categoria_nome", "subcategoria_nome", "produto", mode="before")
    @classmethod
    def _strip_str(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _normalize_blocks(self) -> "ClassificadorClassificationResponse":
        """Limpa blocos opcionais marcados como nao-aplicaveis."""
        # Se patrocinio.aplicavel=false, limpa demais campos do bloco
        if self.patrocinio and not self.patrocinio.aplicavel:
            self.patrocinio.decisao = None
            self.patrocinio.outro_escritorio_nome = None
            self.patrocinio.outro_advogado_nome = None
            self.patrocinio.outro_advogado_oab = None
            self.patrocinio.outro_advogado_data_habilitacao = None
            self.patrocinio.suspeita_devolucao = False
            self.patrocinio.motivo_suspeita = None

        # Se contestacao.existe=false, limpa
        if self.contestacao_existente and not self.contestacao_existente.existe:
            self.contestacao_existente.apresentada_por_mdr = None
            self.contestacao_existente.apresentada_por_nome = None
            self.contestacao_existente.apresentada_por_oab = None
            self.contestacao_existente.parte_representada = None
            self.contestacao_existente.data_apresentacao = None
            self.contestacao_existente.generica = None
            self.contestacao_existente.analise_qualidade = None

        # Sentenca: limpa se nao existe
        if self.sentenca and not self.sentenca.existe:
            self.sentenca.data = None
            self.sentenca.tipo = None
            self.sentenca.resumo = None
            self.sentenca.valor_condenacao = None
            self.sentenca.fundamentacao = None

        # Transito: limpa se nao transitado
        if self.transito_julgado and not self.transito_julgado.transitado:
            self.transito_julgado.data = None
            self.transito_julgado.fundamentacao = None

        # Primeira habilitacao Master: limpa se nao existe
        if self.primeira_habilitacao_master and not self.primeira_habilitacao_master.existe:
            self.primeira_habilitacao_master.advogado_nome = None
            self.primeira_habilitacao_master.advogado_oab = None
            self.primeira_habilitacao_master.escritorio_nome = None
            self.primeira_habilitacao_master.data_habilitacao = None
            self.primeira_habilitacao_master.parte_representada = None

        return self


__all__ = [
    "ClassificadorClassificationResponse",
    "PedidoResponse",
    "PatrocinioResponse",
    "ContestacaoExistenteResponse",
    "SentencaResponse",
    "TransitoJulgadoResponse",
    "PrimeiraHabilitacaoMasterResponse",
    "PoloMdr",
    "NaturezaProcesso",
    "ProbabilidadePerda",
    "Confianca",
    "PatrocinioDecisao",
    "NaturezaAcao",
    "SentencaTipo",
]
