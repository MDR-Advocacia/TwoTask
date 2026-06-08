"""Modelos da varredura de andamentos.

Feature incidental (sem deploy em main) que entra nos processos onde o
MDR e' responsavel master + cliente no polo passivo, abre a pagina de
andamentos do L1 (DetailsAndamentos) e raspa textos atras de eventos
relevantes: audiencia designada/cancelada, sentenca, revelia,
transito em julgado, arquivamento.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.session import Base


# ── Status da run (1 linha por execucao do operador) ──────────────────

RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_DONE = "DONE"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUS_CANCELLED = "CANCELLED"

ALL_RUN_STATUSES = (
    RUN_STATUS_RUNNING,
    RUN_STATUS_DONE,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELLED,
)


# ── Status do item de fila (1 linha por processo dentro da run) ───────

QUEUE_STATUS_PENDING = "PENDENTE"
QUEUE_STATUS_PROCESSING = "PROCESSANDO"
QUEUE_STATUS_COMPLETED = "CONCLUIDO"
QUEUE_STATUS_FAILED = "FALHA"

ALL_QUEUE_STATUSES = (
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_FAILED,
)


# ── Tipos de evento detectaveis (1:1 com o catalogo do regex_eventos) ─

EVENTO_AUDIENCIA_DESIGNADA = "audiencia_designada"
EVENTO_AUDIENCIA_CANCELADA = "audiencia_cancelada"
EVENTO_SENTENCA = "sentenca"
EVENTO_REVELIA = "revelia"
EVENTO_TRANSITO_JULGADO = "transito_julgado"
EVENTO_ARQUIVAMENTO = "arquivamento"
EVENTO_CUMPRIMENTO_INICIADO = "cumprimento_iniciado"
EVENTO_CUMPRIMENTO_EXTINTO = "cumprimento_extinto"

ALL_TIPOS_EVENTO = (
    EVENTO_AUDIENCIA_DESIGNADA,
    EVENTO_AUDIENCIA_CANCELADA,
    EVENTO_SENTENCA,
    EVENTO_REVELIA,
    EVENTO_TRANSITO_JULGADO,
    EVENTO_ARQUIVAMENTO,
    EVENTO_CUMPRIMENTO_INICIADO,
    EVENTO_CUMPRIMENTO_EXTINTO,
)


# ── Tabelas ───────────────────────────────────────────────────────────


class VarreduraRun(Base):
    __tablename__ = "varredura_run"

    id = Column(Integer, primary_key=True)
    status = Column(
        String(16),
        nullable=False,
        default=RUN_STATUS_RUNNING,
        server_default=RUN_STATUS_RUNNING,
    )
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # Lista de external_id de LegalOneOffice selecionados pelo operador.
    responsible_office_ids = Column(JSON, nullable=False)
    window_days = Column(
        Integer, nullable=False, default=30, server_default="30"
    )
    total_processos = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_processados = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_achados = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_falhas = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    triggered_by = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)

    processados = relationship(
        "VarreduraProcessado",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    achados = relationship(
        "VarreduraAchado",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class VarreduraProcessado(Base):
    __tablename__ = "varredura_processado"

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("varredura_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    lawsuit_id = Column(Integer, nullable=False)
    cnj_number = Column(String(64), nullable=True)
    office_id = Column(Integer, nullable=True)
    queue_status = Column(
        String(16),
        nullable=False,
        default=QUEUE_STATUS_PENDING,
        server_default=QUEUE_STATUS_PENDING,
    )
    attempt_count = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    total_andamentos_lidos = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_achados = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error = Column(Text, nullable=True)
    last_reason = Column(String(64), nullable=True)
    # Snapshot da capa da planilha (Listagem L1) no momento da varredura.
    # Permite queries cruzadas sem reler a planilha. Var002 (2026-06-07).
    capa_json = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    run = relationship("VarreduraRun", back_populates="processados")
    achados = relationship(
        "VarreduraAchado",
        back_populates="processado",
        cascade="all, delete-orphan",
    )
    andamentos_raw = relationship(
        "VarreduraAndamentoRaw",
        back_populates="processado",
        cascade="all, delete-orphan",
    )


class VarreduraAchado(Base):
    __tablename__ = "varredura_achado"

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("varredura_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    processado_id = Column(
        Integer,
        ForeignKey("varredura_processado.id", ondelete="CASCADE"),
        nullable=False,
    )
    lawsuit_id = Column(Integer, nullable=False)
    cnj_number = Column(String(64), nullable=True)
    andamento_data = Column(Date, nullable=True)
    andamento_hora = Column(String(8), nullable=True)
    andamento_tipo = Column(String(64), nullable=True)
    andamento_texto = Column(Text, nullable=False)
    andamento_movimentado_por = Column(String(255), nullable=True)
    tipo_evento = Column(String(32), nullable=False)
    regex_matched = Column(Text, nullable=True)
    tratado = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    tratado_em = Column(DateTime(timezone=True), nullable=True)
    tratado_por = Column(String(255), nullable=True)
    observacao = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run = relationship("VarreduraRun", back_populates="achados")
    processado = relationship(
        "VarreduraProcessado", back_populates="achados"
    )


class VarreduraAndamentoRaw(Base):
    """TODOS os andamentos brutos varridos (nao so' os que matcham regex).

    Permite consultas livres: distribuicao de tipos por UF, busca textual,
    timeline de processos, etc. Adicionada em var002 (2026-06-07).
    """

    __tablename__ = "varredura_andamento_raw"

    id = Column(BigInteger, primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("varredura_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    processado_id = Column(
        Integer,
        ForeignKey("varredura_processado.id", ondelete="CASCADE"),
        nullable=False,
    )
    lawsuit_id = Column(Integer, nullable=False)
    cnj_number = Column(String(64), nullable=True)
    office_id = Column(Integer, nullable=True)
    andamento_data = Column(Date, nullable=True)
    andamento_hora = Column(String(8), nullable=True)
    andamento_tipo = Column(String(64), nullable=True)
    andamento_texto = Column(Text, nullable=False)
    andamento_movimentado_por = Column(String(255), nullable=True)
    ordem = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    processado = relationship(
        "VarreduraProcessado", back_populates="andamentos_raw"
    )
