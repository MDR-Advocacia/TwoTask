"""Modelos do módulo OneRequest (DMIs do Banco do Brasil).

O OneRequest acompanha as DMIs (demandas diversas de assessoria) que chegam
pelo Portal Jurídico do BB. A captura continua sendo feita por um MOTOR RPA
EXTERNO (máquina do escritório, IP autorizado no BB) — ver
`docs/onerequest-integracao-plano.md`. Esse motor empurra os dados pra cá via
os endpoints de intake (`/api/v1/onerequest/intake/*`); o tratamento e o
agendamento no Legal One acontecem dentro do Flow.

Tabela (prefixo onr*):
- onr_solicitacoes — uma linha por DMI (número da solicitação é a chave).
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.db.session import Base

# ── status_sistema: espelha o lado do BB ──────────────────────────────
# ABERTO     -> a DMI ainda aparece na fila do portal do BB.
# RESPONDIDO -> sumiu do portal (o BB considera respondida). É o sinal que
#               o diff do intake de números calcula automaticamente.
STATUS_SISTEMA_ABERTO = "ABERTO"
STATUS_SISTEMA_RESPONDIDO = "RESPONDIDO"

# ── status_tratamento: o fluxo interno do Flow ────────────────────────
# NOVO                 -> capturada, ainda sem tratamento do operador.
# AGENDADO             -> tarefa criada no L1 (created_task_id preenchido).
# IGNORADO             -> operador marcou como sem providência.
# ERRO                 -> falha ao agendar no L1 (ver last_error).
# AGUARDANDO_PROCESSO  -> sem CNJ/processo resolvível ainda (ex.: BB autor
#                         recém-distribuído). Não é erro: a RPA re-tenta e o
#                         operador pode resolver manualmente. Ver §7 do plano.
STATUS_TRATAMENTO_NOVO = "NOVO"
STATUS_TRATAMENTO_AGENDADO = "AGENDADO"
STATUS_TRATAMENTO_IGNORADO = "IGNORADO"
STATUS_TRATAMENTO_ERRO = "ERRO"
STATUS_TRATAMENTO_AGUARDANDO_PROCESSO = "AGUARDANDO_PROCESSO"


class OnerequestSolicitacao(Base):
    __tablename__ = "onr_solicitacoes"

    id = Column(Integer, primary_key=True, index=True)

    # Chave natural da DMI (ex.: "2026/0000000001"). Vem do robô 1 (números).
    numero_solicitacao = Column(String, nullable=False, unique=True, index=True)

    # ── Dados capturados pela RPA (robô 2 — detalhes) ─────────────────
    titulo = Column(String, nullable=True)
    # NPJ Direcionador do BB (formato AAAA/NNNNNNN-NNN). Chave alternativa de
    # resolução do processo no L1 quando o CNJ não vem (ver §7 do plano).
    npj_direcionador = Column(String, nullable=True, index=True)
    # Prazo do BB (DD/MM/YYYY). ATENÇÃO: no agendamento vira o `vencimento`
    # (só aparece na descrição da tarefa), NÃO a data da tarefa. Ver §6 do plano.
    prazo = Column(String, nullable=True)
    texto_dmi = Column(Text, nullable=True)
    # CNJ (20 dígitos) resolvido pela API interna do BB. Pode vir vazio ou
    # "sujo" (~3% dos casos) — nesses, resolve-se por NPJ ou trata manual.
    numero_processo = Column(String, nullable=True, index=True)
    polo = Column(String, nullable=True)  # "Ativo" / "Passivo" / etc.

    # Quando entrou (1º intake de números) — alimenta o gráfico de recebimentos.
    recebido_em = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    # Quando os detalhes foram preenchidos (robô 2).
    detalhe_capturado_em = Column(DateTime(timezone=True), nullable=True)

    status_sistema = Column(
        String, nullable=False, server_default=STATUS_SISTEMA_ABERTO, index=True
    )
    status_tratamento = Column(
        String, nullable=False, server_default=STATUS_TRATAMENTO_NOVO, index=True
    )

    # ── Campos de tratamento (preenchidos pelo operador na UI — Fase 2) ──
    responsavel_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    setor = Column(String, nullable=True)  # mapeia (typeId, subtypeId) no L1
    # Data de agendamento escolhida pelo operador (DD/MM/YYYY). ATENÇÃO: é ela
    # que vira o `prazo` da tarefa no L1 (dirige start/endDateTime). Ver §6.
    data_agendamento = Column(String, nullable=True)
    anotacao = Column(Text, nullable=True)

    # ── Resultado do agendamento no L1 ────────────────────────────────
    created_task_id = Column(Integer, nullable=True, index=True)
    linked_lawsuit_id = Column(Integer, nullable=True, index=True)
    last_error = Column(Text, nullable=True)

    # ── Acompanhamento no L1 (sob demanda — botão "Atualizar status L1") ──
    # Cacheia a última checagem do Legal One pra "planilha" mostrar o sinal
    # sem re-consultar a cada reload. Ver service.verificar_status_l1.
    # Quando foi a última checagem (None = nunca checado).
    l1_checked_at = Column(DateTime(timezone=True), nullable=True)
    # Tarefa da DMI achada na pasta (match por nº da solicitação na descrição).
    # None = não encontrada (mesmo tendo checado).
    l1_dmi_task_id = Column(Integer, nullable=True)
    # Status dessa tarefa: 0 Pendente, 1 Cumprido, 2 Não cumprido, 3 Cancelado,
    # 4 Iniciado, 5 Reagendado. "Respondida no L1" = 1 (Cumprido).
    l1_dmi_status_id = Column(Integer, nullable=True)
    # Nº de tarefas Pendente/Iniciado na pasta (0 = sem pendência). None = não checado.
    l1_pendentes_count = Column(Integer, nullable=True)

    # ── Verificação proativa de existência do processo no L1 (onr004) ──
    # Resolve CNJ->NPJ SEM criar tarefa, só pra sinalizar no painel se a pasta
    # existe no L1 antes do agendamento. Ver service.verificar_processo_l1.
    # None = não checado; True = pasta achada; False = checado e não achado.
    proc_l1_checado_em = Column(DateTime(timezone=True), nullable=True)
    proc_l1_encontrado = Column(Boolean, nullable=True)
    proc_l1_via = Column(String, nullable=True)  # "cnj" / "npj" / "cache"

    # ── Auditoria do agendamento (padrão de Publicações, pub002) ──────
    scheduled_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    scheduled_by_email = Column(String, nullable=True)
    scheduled_by_nome = Column(String, nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class OnerequestAnotacao(Base):
    """Log append-only de anotações por DMI (auditoria: quem/quando/texto).

    Ex.: "usuário respondeu atrasado em 12/06". Não substitui o campo
    `anotacao` (nota rápida) da solicitação — é o histórico formal.
    """

    __tablename__ = "onr_anotacoes"

    id = Column(Integer, primary_key=True, index=True)
    solicitacao_id = Column(
        Integer,
        ForeignKey("onr_solicitacoes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    texto = Column(Text, nullable=False)
    autor_user_id = Column(
        Integer, ForeignKey("legal_one_users.id", ondelete="SET NULL"), nullable=True
    )
    autor_nome = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
