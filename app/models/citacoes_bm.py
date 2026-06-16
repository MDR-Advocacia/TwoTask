"""Modelos do módulo Citações BM (Banco Master).

Monitora processos do escritório "Banco Master / Réu" via DataJud (API
pública do CNJ) para detectar a CITAÇÃO efetiva — gatilho da habilitação.
O sistema só TRAZ as movimentações; quem decide se houve citação é o
operador (status_citacao é alterado exclusivamente por ele).

Tabelas (prefixo cit*):
- cit_processos  — processo monitorado (1 por CNJ).
- cit_movimentos — movimentações capturadas do DataJud (N por processo).
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base

# Status do processo no fluxo de citação. Alterado EXCLUSIVAMENTE pelo
# operador (o scan automático nunca mexe nisto).
STATUS_PENDENTE = "PENDENTE"
STATUS_CITADO = "CITADO"
STATUS_NAO_CITADO = "NAO_CITADO"

# De onde o processo entrou no monitoramento.
ORIGEM_LISTA = "LISTA_MANUAL"
ORIGEM_L1_AUTO = "L1_AUTO"

# Resultado da última varredura no DataJud.
SCAN_OK = "OK"
SCAN_SEM_HITS = "SEM_HITS"  # DataJud ainda não tem o processo (lag do tribunal)
SCAN_ERRO = "ERRO"


class CitacaoBMProcesso(Base):
    __tablename__ = "cit_processos"

    id = Column(Integer, primary_key=True, index=True)

    # CNJ só com dígitos (20) é a chave canônica; máscara é só pra exibição.
    cnj = Column(String(25), nullable=False, unique=True, index=True)
    cnj_mask = Column(String(40), nullable=True)

    # Resolução no Legal One (pode faltar se o processo ainda não tem pasta).
    lawsuit_id = Column(Integer, nullable=True, index=True)
    office_external_id = Column(Integer, nullable=True, index=True)
    office_path = Column(String, nullable=True)
    l1_creation_date = Column(DateTime(timezone=True), nullable=True)

    # Roteamento DataJud + metadados de exibição.
    tribunal_alias = Column(String(40), nullable=True)
    uf = Column(String(4), nullable=True)
    cidade = Column(String, nullable=True)
    acao = Column(String, nullable=True)
    cliente = Column(String, nullable=True)
    contrario = Column(String, nullable=True)

    origem = Column(String(16), nullable=False, default=ORIGEM_LISTA)

    # Decisão do operador.
    status_citacao = Column(
        String(16), nullable=False, default=STATUS_PENDENTE, index=True
    )
    citado_por_user_id = Column(Integer, nullable=True)
    citado_por_nome = Column(String, nullable=True)
    citado_em = Column(DateTime(timezone=True), nullable=True)
    observacao = Column(Text, nullable=True)

    # Vira False quando o operador marca CITADO (arquiva → sai da varredura).
    monitoramento_ativo = Column(
        Boolean, nullable=False, default=True, index=True
    )

    # Estado da varredura DataJud + contadores denormalizados (lista rápida).
    last_scan_at = Column(DateTime(timezone=True), nullable=True)
    last_scan_status = Column(String(16), nullable=True)
    last_scan_error = Column(Text, nullable=True)
    last_movement_at = Column(DateTime(timezone=True), nullable=True)
    total_movimentos = Column(Integer, nullable=False, default=0)
    novos_movimentos = Column(Integer, nullable=False, default=0)
    tem_candidato_citacao = Column(Boolean, nullable=False, default=False)

    created_by_email = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    movimentos = relationship(
        "CitacaoBMMovimento",
        back_populates="processo",
        cascade="all, delete-orphan",
        order_by="CitacaoBMMovimento.data_hora.desc()",
    )


class CitacaoBMMovimento(Base):
    __tablename__ = "cit_movimentos"
    __table_args__ = (
        # Dedupe: cada fingerprint é único dentro do processo.
        UniqueConstraint("processo_id", "fingerprint", name="uq_cit_mov_fp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    processo_id = Column(
        Integer,
        ForeignKey("cit_processos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    codigo_tpu = Column(Integer, nullable=True)
    nome = Column(String, nullable=False)
    grau = Column(String(8), nullable=True)
    data_hora = Column(DateTime(timezone=True), nullable=True, index=True)
    complementos = Column(JSONB, nullable=True)
    orgao_julgador = Column(String, nullable=True)

    # Hash estável (grau+codigo+data+nome+complementos) pra evitar reinserção.
    fingerprint = Column(String(64), nullable=False, index=True)

    # Heurística de citação — só DESTACA; quem decide é o operador.
    is_candidato_citacao = Column(
        Boolean, nullable=False, default=False, index=True
    )
    cit_match_termo = Column(String, nullable=True)

    # Não-lido = movimento novo desde a última visita do operador.
    lido = Column(Boolean, nullable=False, default=False, index=True)
    captured_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    processo = relationship("CitacaoBMProcesso", back_populates="movimentos")
