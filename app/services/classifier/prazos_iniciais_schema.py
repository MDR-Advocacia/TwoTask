"""
Schema Pydantic da resposta da IA no fluxo "Agendar Prazos Iniciais".

A IA (Claude Sonnet) recebe a capa + íntegra de um processo e precisa
responder 6 perguntas. Cada resposta vira uma ou mais sugestões em
`prazo_inicial_sugestao`. A taxonomia que mapeia `tipo_prazo` →
`task_type_id`/`task_subtype_id` do Legal One está *deliberadamente fora*
deste módulo — será definida em sessão dedicada. Aqui só garantimos que
o JSON retornado pelo modelo seja válido e navegável.

As 6 perguntas:

1. Determinação para CONTESTAR  → `contestar`
2. Determinação para CUMPRIR LIMINAR → `liminar`
3. Determinação para MANIFESTAÇÃO AVULSA → `manifestacao_avulsa`
4. AUDIÊNCIA marcada → `audiencia`
5. NENHUMA determinação para a Ré → `sem_determinacao` (bool)
6. Já existe JULGAMENTO → `julgamento`

Convenção: quando `sem_determinacao=True`, espera-se que os blocos 1-4 e
o bloco 6 tenham `aplica=False`. Se vierem divergentes, `sem_determinacao`
tem precedência (o modelo pode errar; a revisão humana ajusta).
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

TIPOS_PRAZO_VALIDOS = frozenset({
    TIPO_PRAZO_CONTESTAR,
    TIPO_PRAZO_LIMINAR,
    TIPO_PRAZO_MANIFESTACAO_AVULSA,
    TIPO_PRAZO_AUDIENCIA,
    TIPO_PRAZO_JULGAMENTO,
    TIPO_PRAZO_SEM_DETERMINACAO,
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

    Uma única intake gera N sugestões: uma por bloco com `aplica=True`,
    ou uma sugestão do tipo SEM_DETERMINACAO quando `sem_determinacao=True`.
    """

    # Pergunta 5 (flag guarda-chuva).
    sem_determinacao: bool = False

    # Perguntas 1-4, 6.
    contestar: BlocoContestar
    liminar: BlocoLiminar
    manifestacao_avulsa: BlocoManifestacaoAvulsa
    audiencia: BlocoAudiencia
    julgamento: BlocoJulgamento

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
        )
        if self.sem_determinacao and qualquer_bloco_aplica:
            # Conflito: prioriza os blocos específicos.
            self.sem_determinacao = False
        return self

    def blocos_aplicaveis(self) -> list[tuple[str, BaseModel]]:
        """
        Retorna (tipo_prazo, bloco) para cada bloco com `aplica=True`.
        Se `sem_determinacao=True` (e nenhum bloco aplica), retorna um
        único item com tipo SEM_DETERMINACAO (bloco = None-ish via instância
        vazia do BaseModel). O chamador é quem materializa em
        `PrazoInicialSugestao`.
        """
        pares: list[tuple[str, BaseModel]] = []
        if self.contestar.aplica:
            pares.append((TIPO_PRAZO_CONTESTAR, self.contestar))
        if self.liminar.aplica:
            pares.append((TIPO_PRAZO_LIMINAR, self.liminar))
        if self.manifestacao_avulsa.aplica:
            pares.append((TIPO_PRAZO_MANIFESTACAO_AVULSA, self.manifestacao_avulsa))
        if self.audiencia.aplica:
            pares.append((TIPO_PRAZO_AUDIENCIA, self.audiencia))
        if self.julgamento.aplica:
            pares.append((TIPO_PRAZO_JULGAMENTO, self.julgamento))
        if not pares and self.sem_determinacao:
            pares.append((TIPO_PRAZO_SEM_DETERMINACAO, self))
        return pares
