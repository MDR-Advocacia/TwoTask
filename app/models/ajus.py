"""
Modelos do módulo AJUS — integração com a API do sistema do cliente.

A AJUS expõe um endpoint `POST /inserir-prazos` (ver
`docs/api-ajus-resumo.md` ou a doc oficial) que aceita até 20 itens por
chamada. Cada item representa um "andamento" no AJUS — embora o nome do
endpoint seja "inserir-prazos", no domínio AJUS um andamento é
materializado como um prazo (com `codAndamento` no payload).

Aqui modelamos só o necessário pro fluxo MDR:
- `AjusCodAndamento`: catálogo de códigos disponíveis (admin cadastra
  conforme a equipe AJUS fornece). Cada código é um TEMPLATE: define
  o que vai pro payload (situação, offsets das datas, texto base).
- `AjusAndamentoQueue`: fila de itens a serem enviados pra AJUS. Um
  intake de prazos iniciais que entra com status RECEBIDO gera 1 item
  na fila automaticamente, snapshot dos campos do template aplicado.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


# ─── Status da fila ───────────────────────────────────────────────────
AJUS_QUEUE_PENDENTE = "pendente"
AJUS_QUEUE_ENVIANDO = "enviando"
AJUS_QUEUE_SUCESSO = "sucesso"
AJUS_QUEUE_ERRO = "erro"
AJUS_QUEUE_CANCELADO = "cancelado"

AJUS_QUEUE_STATUSES = frozenset({
    AJUS_QUEUE_PENDENTE,
    AJUS_QUEUE_ENVIANDO,
    AJUS_QUEUE_SUCESSO,
    AJUS_QUEUE_ERRO,
    AJUS_QUEUE_CANCELADO,
})

# Situação do prazo na AJUS — A=aberto, C=concluído.
AJUS_SITUACAO_ABERTO = "A"
AJUS_SITUACAO_CONCLUIDO = "C"


class AjusCodAndamento(Base):
    """
    Catálogo de códigos de andamento da AJUS + template do payload.

    Quando um intake é enfileirado automaticamente, o sistema usa o
    registro com `is_default=True` (deve haver no máximo um — partial
    unique index garante). Operador pode editar offsets e
    `informacao_template` sem deploy.

    O `informacao_template` aceita placeholders simples interpolados no
    momento do enfileiramento:
      - {cnj}            — número do processo do intake
      - {data_recebimento} — data de criação do intake (dd/MM/yyyy)
    """

    __tablename__ = "ajus_cod_andamento"
    __table_args__ = (
        CheckConstraint(
            "situacao IN ('A','C')", name="ck_ajus_cod_andamento_situacao",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Código que vai literal no payload AJUS.
    codigo = Column(String(64), nullable=False, unique=True, index=True)
    label = Column(String(200), nullable=False)
    descricao = Column(Text, nullable=True)

    # ── Template do payload pra esse código ──
    situacao = Column(String(1), nullable=False, default="A")
    dias_agendamento_offset_uteis = Column(Integer, nullable=False, default=3)
    dias_fatal_offset_uteis = Column(Integer, nullable=False, default=15)
    informacao_template = Column(
        Text,
        nullable=False,
        default="Andamento — processo {cnj}.",
    )

    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AjusAndamentoQueue(Base):
    """
    Item de fila do AJUS — 1 intake → 1 item (unique em intake_id).

    Snapshot: quando enfileirado, copiamos os campos do template do
    `AjusCodAndamento` pros próprios campos da fila. Mudanças
    posteriores no template NÃO refletem em itens já enfileirados.
    Isso preserva auditoria e permite o operador editar o item antes
    de disparar (caso tenha que ajustar uma data específica).

    PDF: copiado pra storage próprio da AJUS (`AJUS_STORAGE_PATH`)
    pra sobreviver à rotina de cleanup do prazos iniciais. Quando o
    AJUS retorna sucesso (`cod_informacao_judicial` preenchido), a
    cópia é apagada — assim só guardamos PDFs de itens em pendente
    ou erro (que precisam de retry).
    """

    __tablename__ = "ajus_andamento_queue"
    __table_args__ = (
        CheckConstraint(
            "situacao IN ('A','C')", name="ck_ajus_queue_situacao",
        ),
        CheckConstraint(
            "status IN ('pendente','enviando','sucesso','erro','cancelado')",
            name="ck_ajus_queue_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    intake_id = Column(
        Integer,
        ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    cnj_number = Column(String(25), nullable=False, index=True)

    cod_andamento_id = Column(
        Integer,
        ForeignKey("ajus_cod_andamento.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Snapshot do payload no momento do enfileiramento
    situacao = Column(String(1), nullable=False)
    data_evento = Column(Date, nullable=False)
    data_agendamento = Column(Date, nullable=False)
    data_fatal = Column(Date, nullable=False)
    hora_agendamento = Column(Time, nullable=True)
    informacao = Column(Text, nullable=False)

    # Caminho RELATIVO da cópia do PDF dentro do storage AJUS.
    pdf_path = Column(String(512), nullable=True)

    status = Column(
        String(16), nullable=False, default="pendente", index=True,
    )
    cod_informacao_judicial = Column(String(64), nullable=True, unique=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    cod_andamento = relationship(
        "AjusCodAndamento",
        primaryjoin="AjusAndamentoQueue.cod_andamento_id == AjusCodAndamento.id",
        foreign_keys=[cod_andamento_id],
    )
    intake = relationship(
        "PrazoInicialIntake",
        primaryjoin="AjusAndamentoQueue.intake_id == PrazoInicialIntake.id",
        foreign_keys=[intake_id],
    )


# ═══════════════════════════════════════════════════════════════════════
# Módulo de Classificação AJUS (Chunk 1 — Mirror porting)
# ═══════════════════════════════════════════════════════════════════════
# Para o AJUS reconhecer um andamento e gerar remuneração ao escritório,
# a pasta do processo precisa estar CLASSIFICADA na capa (5 campos: UF,
# Comarca, Matéria, Justiça/Honorário, Risco/Prob. Perda). O Mirror já
# fazia isso via RPA Playwright com 100% de sucesso. Aqui modelamos a
# fila e os defaults — o runner Playwright vem no Chunk 2.

# Status da fila de classificação
AJUS_CLASSIF_PENDENTE = "pendente"
AJUS_CLASSIF_PROCESSANDO = "processando"
AJUS_CLASSIF_SUCESSO = "sucesso"
AJUS_CLASSIF_ERRO = "erro"
AJUS_CLASSIF_CANCELADO = "cancelado"

AJUS_CLASSIF_STATUSES = frozenset({
    AJUS_CLASSIF_PENDENTE,
    AJUS_CLASSIF_PROCESSANDO,
    AJUS_CLASSIF_SUCESSO,
    AJUS_CLASSIF_ERRO,
    AJUS_CLASSIF_CANCELADO,
})

# Origem do item na fila de classificação
AJUS_CLASSIF_ORIGEM_INTAKE = "intake_auto"
AJUS_CLASSIF_ORIGEM_PLANILHA = "planilha"


class AjusClassificacaoDefaults(Base):
    """
    Singleton (id=1) com defaults usados pra preencher os campos quando
    o intake de prazos iniciais é enfileirado automaticamente.

    Operador admin edita pela UI: define `default_matter` (ex.:
    "Cumprimento de Sentença") e `default_risk_loss_probability` (ex.:
    "Remoto"). Sem isso preenchido, intake_auto fica com NULL nesses
    campos e o operador edita por linha antes de disparar.
    """

    __tablename__ = "ajus_classificacao_defaults"
    __table_args__ = (
        # CHECK que garante singleton (apenas id=1 permitido).
        # Definido na migration via raw SQL.
    )

    id = Column(Integer, primary_key=True)
    default_matter = Column(String(255), nullable=True)
    default_risk_loss_probability = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AjusClassificacaoQueue(Base):
    """
    Fila de processos a classificar na capa do AJUS via RPA Playwright.

    1 CNJ = 1 item (UNIQUE). Se o operador subir o mesmo CNJ duas vezes
    (planilha) ou se um intake duplicado tentar enfileirar, a segunda
    inserção é ignorada/atualizada conforme caller.

    Origens:
      - `intake_auto`: criado pelo hook do intake_service quando intake
        passa pra status RECEBIDO. Preenche UF (do CNJ), Comarca
        (Jurisdição do intake -> fallback vara), Matéria + Risco
        (defaults). `justice_fee` fica NULL — operador edita.
      - `planilha`: upload XLSX com TODOS os campos preenchidos pelo
        operador. Mais controlado, usado pra estoque legado.
    """

    __tablename__ = "ajus_classificacao_queue"
    __table_args__ = (
        CheckConstraint(
            "origem IN ('intake_auto','planilha')",
            name="ck_ajus_classif_queue_origem",
        ),
        CheckConstraint(
            "status IN ('pendente','processando','sucesso','erro','cancelado')",
            name="ck_ajus_classif_queue_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    cnj_number = Column(String(25), nullable=False, unique=True, index=True)
    intake_id = Column(
        Integer,
        ForeignKey("prazo_inicial_intakes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    origem = Column(String(16), nullable=False, index=True)

    # Campos da capa do processo no AJUS
    uf = Column(String(8), nullable=True)
    comarca = Column(String(255), nullable=True)
    matter = Column(String(255), nullable=True)
    justice_fee = Column(String(255), nullable=True)
    risk_loss_probability = Column(String(255), nullable=True)

    status = Column(
        String(16), nullable=False, default="pendente", index=True,
    )
    error_message = Column(Text, nullable=True)
    last_log = Column(Text, nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # FK pra conta que executou o dispatch (Chunk 2). NULL enquanto
    # pendente; preenchido quando dispatcher pega o item. Permite
    # filtrar histórico por conta.
    dispatched_by_account_id = Column(
        Integer,
        ForeignKey("ajus_session_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationship
    intake = relationship(
        "PrazoInicialIntake",
        primaryjoin="AjusClassificacaoQueue.intake_id == PrazoInicialIntake.id",
        foreign_keys=[intake_id],
    )
    dispatched_by_account = relationship(
        "AjusSessionAccount",
        primaryjoin=(
            "AjusClassificacaoQueue.dispatched_by_account_id == "
            "AjusSessionAccount.id"
        ),
        foreign_keys=[dispatched_by_account_id],
    )


# ═══════════════════════════════════════════════════════════════════════
# Sessão AJUS — multi-conta (Chunk 2 — runner Playwright)
# ═══════════════════════════════════════════════════════════════════════
# Pra rodar a classificação na capa do AJUS via RPA precisamos de
# sessões autenticadas. O cliente do MDR usa várias contas humanas que
# também são usadas pelo robô — diluir tráfego entre N contas evita
# rate-limit, ganha throughput pra zerar o backlog (~2.300 processos)
# e adiciona resiliência (se uma conta cair na validação de IP, as
# outras continuam).

# Status da conta — ver docstring da migration ajus003.
AJUS_ACCOUNT_OFFLINE = "offline"
AJUS_ACCOUNT_LOGANDO = "logando"
AJUS_ACCOUNT_AGUARDANDO_IP = "aguardando_ip_code"
AJUS_ACCOUNT_ONLINE = "online"
AJUS_ACCOUNT_EXECUTANDO = "executando"
AJUS_ACCOUNT_ERRO = "erro"

AJUS_ACCOUNT_STATUSES = frozenset({
    AJUS_ACCOUNT_OFFLINE,
    AJUS_ACCOUNT_LOGANDO,
    AJUS_ACCOUNT_AGUARDANDO_IP,
    AJUS_ACCOUNT_ONLINE,
    AJUS_ACCOUNT_EXECUTANDO,
    AJUS_ACCOUNT_ERRO,
})


class AjusSessionAccount(Base):
    """
    Conta de operador no AJUS usada pelo runner Playwright.

    Senha vai criptografada (Fernet, env `AJUS_FERNET_KEY`). O
    `storage_state_path` aponta pra um arquivo dentro do volume
    persistente `/data/ajus-session/` mantido pelo container
    `ajus-runner` (Chunk 2c). Status muda conforme o flow do runner.
    """

    __tablename__ = "ajus_session_accounts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('offline','logando','aguardando_ip_code',"
            "'online','executando','erro')",
            name="ck_ajus_session_accounts_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    label = Column(String(64), nullable=False, unique=True)
    login = Column(String(128), nullable=False)
    encrypted_password = Column(Text, nullable=False)
    storage_state_path = Column(String(255), nullable=True)

    status = Column(
        String(24), nullable=False, default=AJUS_ACCOUNT_OFFLINE, index=True,
    )
    pending_ip_code = Column(String(32), nullable=True)

    last_error_message = Column(Text, nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, index=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
