"""
Schema Pydantic da resposta da IA no fluxo "Agendar Prazos Iniciais".

A IA (Claude Sonnet) recebe a capa + íntegra de um processo e precisa
responder a um conjunto de perguntas roteado pela `natureza_processo`.

Estrutura da resposta:

- `produto` (INFORMATIVO APENAS): qual produto está sendo discutido na
  petição inicial. Não afeta matching de template nem branching.
- `natureza_processo` (ROUTER): Procedimento Comum / Juizado / Agravo
  de Instrumento / Outro. Determina o conjunto de perguntas aplicáveis.

Perguntas por ramo:

**COMUM / JUIZADO / OUTRO** — mesmas 6 perguntas:
  1. Determinação para CONTESTAR  → `contestar`
  2. Determinação para CUMPRIR LIMINAR → `liminar`
  3. Determinação para MANIFESTAÇÃO AVULSA → `manifestacao_avulsa`
  4. AUDIÊNCIA marcada → `audiencia`
  5. NENHUMA determinação para a Ré → `sem_determinacao` (bool)
  6. Já existe JULGAMENTO → `julgamento`

**AGRAVO_INSTRUMENTO** — só:
  7. Determinação para apresentar CONTRARRAZÕES → `contrarrazoes`
  (+ `sem_determinacao` como fallback; audiência e demais blocos são
  ignorados nesse ramo.)

Convenção: quando `sem_determinacao=True`, espera-se que todos os blocos
específicos tenham `aplica=False`. Se vierem divergentes, o conteúdo dos
blocos prevalece e `sem_determinacao` vira False.
"""

from __future__ import annotations

from datetime import date, time
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Tipos de prazo ──────────────────────────────────────────────────
# Valores usados no campo `tipo_prazo` das sugestões persistidas. Ficam
# como constantes pra evitar typos quando a sessão da taxonomia mapear
# cada um para `task_type_id` / `task_subtype_id`.

TIPO_PRAZO_CONTESTAR = "CONTESTAR"
TIPO_PRAZO_LIMINAR = "LIMINAR"
TIPO_PRAZO_MANIFESTACAO_AVULSA = "MANIFESTACAO_AVULSA"
TIPO_PRAZO_AUDIENCIA = "AUDIENCIA"
TIPO_PRAZO_JULGAMENTO = "JULGAMENTO"
TIPO_PRAZO_SEM_DETERMINACAO = "SEM_DETERMINACAO"
TIPO_PRAZO_CONTRARRAZOES = "CONTRARRAZOES"

TIPOS_PRAZO_VALIDOS = frozenset({
    TIPO_PRAZO_CONTESTAR,
    TIPO_PRAZO_LIMINAR,
    TIPO_PRAZO_MANIFESTACAO_AVULSA,
    TIPO_PRAZO_AUDIENCIA,
    TIPO_PRAZO_JULGAMENTO,
    TIPO_PRAZO_SEM_DETERMINACAO,
    TIPO_PRAZO_CONTRARRAZOES,
})


# ─── Natureza do processo (router) ───────────────────────────────────
# Determina o conjunto de perguntas aplicáveis (ver docstring).
# COMUM/JUIZADO/OUTRO compartilham as 6 perguntas clássicas.
# AGRAVO_INSTRUMENTO usa só CONTRARRAZOES (+ SEM_DETERMINACAO fallback).

NATUREZA_COMUM = "COMUM"
NATUREZA_JUIZADO = "JUIZADO"
NATUREZA_AGRAVO_INSTRUMENTO = "AGRAVO_INSTRUMENTO"
NATUREZA_OUTRO = "OUTRO"

NATUREZAS_VALIDAS = frozenset({
    NATUREZA_COMUM,
    NATUREZA_JUIZADO,
    NATUREZA_AGRAVO_INSTRUMENTO,
    NATUREZA_OUTRO,
})

# Ramos que usam as 6 perguntas clássicas.
NATUREZAS_SEIS_PERGUNTAS = frozenset({
    NATUREZA_COMUM,
    NATUREZA_JUIZADO,
    NATUREZA_OUTRO,
})


# ─── Produtos (informativo apenas — não afeta matching) ──────────────

PRODUTO_SUPERENDIVIDAMENTO = "SUPERENDIVIDAMENTO"
PRODUTO_CREDCESTA = "CREDCESTA"
PRODUTO_EMPRESTIMO_CONSIGNADO = "EMPRESTIMO_CONSIGNADO"
PRODUTO_CARTAO_CREDITO_CONSIGNADO = "CARTAO_CREDITO_CONSIGNADO"
PRODUTO_EXIBICAO_DOCUMENTOS = "EXIBICAO_DOCUMENTOS"
PRODUTO_ANULACAO_REVISAO_CONTRATUAL = "ANULACAO_REVISAO_CONTRATUAL"
PRODUTO_NEGATIVACAO_INDEVIDA = "NEGATIVACAO_INDEVIDA"
PRODUTO_LIMITACAO_30 = "LIMITACAO_30"
PRODUTO_GOLPE_FRAUDE = "GOLPE_FRAUDE"
PRODUTO_OUTRO = "OUTRO"

PRODUTOS_VALIDOS = frozenset({
    PRODUTO_SUPERENDIVIDAMENTO,
    PRODUTO_CREDCESTA,
    PRODUTO_EMPRESTIMO_CONSIGNADO,
    PRODUTO_CARTAO_CREDITO_CONSIGNADO,
    PRODUTO_EXIBICAO_DOCUMENTOS,
    PRODUTO_ANULACAO_REVISAO_CONTRATUAL,
    PRODUTO_NEGATIVACAO_INDEVIDA,
    PRODUTO_LIMITACAO_30,
    PRODUTO_GOLPE_FRAUDE,
    PRODUTO_OUTRO,
})


# ─── Blocos de resposta (1 por pergunta com prazo) ───────────────────

PrazoTipo = Literal["util", "corrido"]
Confianca = Literal["alta", "media", "baixa"]


class BlocoPrazoBase(BaseModel):
    """
    Base para respostas das perguntas 1-3 (contestar / liminar / manifestação).

    - `aplica`: se a determinação foi identificada no texto.
    - `prazo_dias` + `prazo_tipo`: tamanho do prazo (apenas quando aplica).
    - `data_base`: data a partir da qual o prazo conta (intimação / ciência /
      publicação). Formato ISO (YYYY-MM-DD).
    - `justificativa`: trecho/frase que embasou a decisão (obrigatório
      sempre — ajuda a revisão humana).
    """

    aplica: bool
    prazo_dias: Optional[int] = Field(default=None, ge=1, le=365)
    prazo_tipo: Optional[PrazoTipo] = None
    data_base: Optional[date] = None
    justificativa: str = ""

    @model_validator(mode="after")
    def _clear_fields_when_not_applicable(self) -> "BlocoPrazoBase":
        """Quando `aplica=False`, ignora campos de prazo que a IA possa
        ter preenchido por engano (evita persistir sugestão com dias mas
        sem determinação)."""
        if not self.aplica:
            self.prazo_dias = None
            self.prazo_tipo = None
            self.data_base = None
        return self


class BlocoContestar(BlocoPrazoBase):
    """Pergunta 1: determinação para contestar."""
    pass


class BlocoLiminar(BlocoPrazoBase):
    """Pergunta 2: determinação para cumprir liminar.

    Campo extra `objeto` descreve o que foi concedido (ex.: "bloqueio de
    valores", "obrigação de fazer"), útil pra montar o payload da tarefa
    depois.
    """

    objeto: Optional[str] = None

    @model_validator(mode="after")
    def _clear_objeto(self) -> "BlocoLiminar":
        if not self.aplica:
            self.objeto = None
        return self


class BlocoManifestacaoAvulsa(BlocoPrazoBase):
    """Pergunta 3: determinação para manifestação avulsa.

    Campo extra `assunto` descreve sobre o quê o juiz pediu manifestação.
    """

    assunto: Optional[str] = None

    @model_validator(mode="after")
    def _clear_assunto(self) -> "BlocoManifestacaoAvulsa":
        if not self.aplica:
            self.assunto = None
        return self


class BlocoContrarrazoes(BlocoPrazoBase):
    """Pergunta 7 (ramo AGRAVO_INSTRUMENTO): determinação para
    apresentar contrarrazões.

    Estrutura idêntica à de CONTESTAR/LIMINAR: prazo textual, sem subtipo.
    `recurso` guarda o nome do recurso agravado (ex.: "agravo de
    instrumento nº ..."), só pra contextualização do payload da tarefa.
    """

    recurso: Optional[str] = None

    @model_validator(mode="after")
    def _clear_recurso(self) -> "BlocoContrarrazoes":
        if not self.aplica:
            self.recurso = None
        return self


class BlocoAudiencia(BaseModel):
    """Pergunta 4: audiência marcada.

    Campos seguem o mesmo padrão usado em publicações (audiencia_data /
    audiencia_hora / audiencia_link), mais `tipo` (conciliação / instrução
    / una / outra) e `endereco` pra audiência presencial.
    """

    aplica: bool
    data: Optional[date] = None
    hora: Optional[time] = None
    tipo: Optional[
        Literal["conciliacao", "instrucao", "una", "outra"]
    ] = None
    link: Optional[str] = None
    endereco: Optional[str] = None
    justificativa: str = ""

    @model_validator(mode="after")
    def _clear_fields_when_not_applicable(self) -> "BlocoAudiencia":
        if not self.aplica:
            self.data = None
            self.hora = None
            self.tipo = None
            self.link = None
            self.endereco = None
        return self


class BlocoJulgamento(BaseModel):
    """Pergunta 6: já existe julgamento.

    Tipo aceita "merito" (procedente / improcedente / parcial), "extincao_sem_merito"
    (150, 485, prescrição, etc.) e "outro" (acórdão, decisão monocrática que
    julga o processo, etc.). Data é quando a sentença/acórdão foi proferido.
    """

    aplica: bool
    tipo: Optional[
        Literal["merito", "extincao_sem_merito", "outro"]
    ] = None
    data: Optional[date] = None
    justificativa: str = ""

    @model_validator(mode="after")
    def _clear_fields_when_not_applicable(self) -> "BlocoJulgamento":
        if not self.aplica:
            self.tipo = None
            self.data = None
        return self


# ─── Resposta completa da IA ─────────────────────────────────────────


class PrazoInicialClassificationResponse(BaseModel):
    """
    Estrutura completa do JSON que a IA deve retornar por intake.

    Classificação preliminar:
    - `produto`: INFORMATIVO APENAS (não afeta matching nem branching).
      Aceita NULL quando o modelo não conseguir inferir com segurança.
    - `natureza_processo`: ROUTER. Determina quais perguntas são
      consideradas. Obrigatório — se o modelo não identificar, retorna
      "OUTRO" (cai no ramo genérico de 6 perguntas).

    Blocos:
    - Ramos COMUM/JUIZADO/OUTRO usam contestar/liminar/manifestacao_avulsa/
      audiencia/julgamento + sem_determinacao. Contrarrazoes vem com
      aplica=False.
    - Ramo AGRAVO_INSTRUMENTO usa só contrarrazoes + sem_determinacao.
      Os demais blocos vêm com aplica=False (o prompt instrui o modelo;
      quaisquer aplica=True em blocos não pertinentes são ignorados em
      `blocos_aplicaveis()`).

    Uma única intake gera N sugestões: uma por bloco `aplica=True`, ou
    uma única SEM_DETERMINACAO quando `sem_determinacao=True`.
    """

    # Classificação preliminar.
    produto: Optional[
        Literal[
            "SUPERENDIVIDAMENTO",
            "CREDCESTA",
            "EMPRESTIMO_CONSIGNADO",
            "CARTAO_CREDITO_CONSIGNADO",
            "EXIBICAO_DOCUMENTOS",
            "ANULACAO_REVISAO_CONTRATUAL",
            "NEGATIVACAO_INDEVIDA",
            "LIMITACAO_30",
            "GOLPE_FRAUDE",
            "OUTRO",
        ]
    ] = None
    natureza_processo: Literal[
        "COMUM", "JUIZADO", "AGRAVO_INSTRUMENTO", "OUTRO"
    ] = "COMUM"
    # COMUM é o default defensivo: se o modelo esquecer o campo, cai no
    # ramo das 6 perguntas clássicas (mais conservador que pular para
    # AGRAVO, onde só CONTRARRAZOES é considerada).

    # Pergunta 5 (flag guarda-chuva).
    sem_determinacao: bool = False

    # Perguntas 1-4, 6 (ramos COMUM/JUIZADO/OUTRO).
    contestar: BlocoContestar
    liminar: BlocoLiminar
    manifestacao_avulsa: BlocoManifestacaoAvulsa
    audiencia: BlocoAudiencia
    julgamento: BlocoJulgamento

    # Pergunta 7 (ramo AGRAVO_INSTRUMENTO). Default aplica=False preserva
    # compatibilidade com testes/fixtures que não conhecem o bloco.
    contrarrazoes: BlocoContrarrazoes = Field(
        default_factory=lambda: BlocoContrarrazoes(aplica=False)
    )

    # Meta.
    confianca_geral: Confianca = "baixa"
    observacoes: Optional[str] = None  # texto livre do modelo, se quiser

    @field_validator("confianca_geral", mode="before")
    @classmethod
    def _normalize_confianca(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
            # pequena tolerância a acentos
            v = v.replace("é", "e").replace("í", "i")
        return v

    @model_validator(mode="after")
    def _enforce_sem_determinacao(self) -> "PrazoInicialClassificationResponse":
        """
        Se `sem_determinacao=True`, força todos os blocos a `aplica=False`.
        Evita que o modelo misture "não há determinação para a Ré" com uma
        audiência marcada — nesse caso, `sem_determinacao` deve ser False
        (há ação pra Ré: comparecer na audiência). Se o modelo retornou
        conflitante, quem ganha é o conteúdo específico (blocos) e tiramos
        o `sem_determinacao`.
        """
        qualquer_bloco_aplica = (
            self.contestar.aplica
            or self.liminar.aplica
            or self.manifestacao_avulsa.aplica
            or self.audiencia.aplica
            or self.julgamento.aplica
            or self.contrarrazoes.aplica
        )
        if self.sem_determinacao and qualquer_bloco_aplica:
            # Conflito: prioriza os blocos específicos.
            self.sem_determinacao = False
        return self

    def blocos_aplicaveis(self) -> list[tuple[str, BaseModel]]:
        """
        Retorna (tipo_prazo, bloco) para cada bloco com `aplica=True`,
        respeitando o branching por `natureza_processo`:

        - AGRAVO_INSTRUMENTO: só considera `contrarrazoes`. Os demais
          blocos são ignorados (defensivo — o prompt já instrui, mas se
          o modelo errar, a gente filtra aqui).
        - Demais naturezas (COMUM/JUIZADO/OUTRO): considera os 5 blocos
          clássicos; `contrarrazoes` é ignorado se vier True.

        Se nenhum bloco aplicar e `sem_determinacao=True`, retorna um
        único item com tipo SEM_DETERMINACAO.
        """
        pares: list[tuple[str, BaseModel]] = []
        if self.natureza_processo == "AGRAVO_INSTRUMENTO":
            if self.contrarrazoes.aplica:
                pares.append((TIPO_PRAZO_CONTRARRAZOES, self.contrarrazoes))
        else:
            if self.contestar.aplica:
                pares.append((TIPO_PRAZO_CONTESTAR, self.contestar))
            if self.liminar.aplica:
                pares.append((TIPO_PRAZO_LIMINAR, self.liminar))
            if self.manifestacao_avulsa.aplica:
                pares.append(
                    (TIPO_PRAZO_MANIFESTACAO_AVULSA, self.manifestacao_avulsa)
                )
            if self.audiencia.aplica:
                pares.append((TIPO_PRAZO_AUDIENCIA, self.audiencia))
            if self.julgamento.aplica:
                pares.append((TIPO_PRAZO_JULGAMENTO, self.julgamento))
        if not pares and self.sem_determinacao:
            pares.append((TIPO_PRAZO_SEM_DETERMINACAO, self))
        return pares
