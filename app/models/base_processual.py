"""Models do modulo Base Processual.

Tabelas:
- BaseProcessualUpload: 1 row por upload (real, dry-run, idempotente, falhou)
- BaseProcessualProcesso: estado atual de cada cod_ajus (chave natural L1)
- BaseProcessualSnapshot: payload por (processo, upload) — audit trail
- BaseProcessualEvento: ENTROU / SAIU / ATUALIZADO / ATUALIZADO_MANUAL
- BaseProcessualApiKey: chaves para consumidores externos

Soft-remove: processo nao e' deletado quando some da planilha — vira
presenca_status=REMOVIDO_NA_BASE, com removed_at_upload_id apontando
pro upload que detectou a saida.

Idempotencia: file_sha256 UNIQUE no upload garante que reupload identico
nao gera estado duplicado.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


# Status do processo na base (presenca)
PRESENCA_ATIVO = "ATIVO_NA_BASE"
PRESENCA_REMOVIDO = "REMOVIDO_NA_BASE"

# Status do upload
UPLOAD_STATUS_PENDENTE = "PENDENTE"
UPLOAD_STATUS_PROCESSANDO = "PROCESSANDO"
UPLOAD_STATUS_CONCLUIDO = "CONCLUIDO"
UPLOAD_STATUS_FALHOU = "FALHOU"
UPLOAD_STATUS_IDEMPOTENTE = "IDEMPOTENTE"
UPLOAD_STATUS_DRY_RUN = "DRY_RUN"
UPLOAD_STATUS_DRY_RUN_EXPIRADO = "DRY_RUN_EXPIRADO"

# Tipos de evento
EVENTO_ENTROU = "ENTROU"
EVENTO_SAIU = "SAIU"
EVENTO_ATUALIZADO = "ATUALIZADO"
EVENTO_ATUALIZADO_MANUAL = "ATUALIZADO_MANUAL"


class BaseProcessualUpload(Base):
    __tablename__ = "base_processual_upload"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(512), nullable=False)
    # NULL pra placeholders (IDEMPOTENTE/FAIL/DRY_RUN) — UNIQUE permite
    # multiplos NULLs em PG, mantendo a constraint pra rows com sha real.
    file_sha256 = Column(String(64), nullable=True, unique=True, index=True)
    file_bytes = Column(Integer, nullable=True)
    total_rows_in_file = Column(Integer, nullable=True)

    summary_novos = Column(Integer, nullable=False, default=0, server_default="0")
    summary_removidos = Column(Integer, nullable=False, default=0, server_default="0")
    summary_atualizados = Column(Integer, nullable=False, default=0, server_default="0")
    summary_inalterados = Column(Integer, nullable=False, default=0, server_default="0")

    status = Column(
        String(32),
        nullable=False,
        default=UPLOAD_STATUS_PENDENTE,
        server_default=UPLOAD_STATUS_PENDENTE,
        index=True,
    )
    error_message = Column(Text, nullable=True)

    # Snapshot leve de eventos previstos no dry-run (lista curta pra UI).
    # Em commit real fica None — detalhe vai pra base_processual_evento.
    eventos_preview_json = Column(JSON, nullable=True)

    dry_run_of_upload_id = Column(
        Integer,
        ForeignKey("base_processual_upload.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    storage_path = Column(String(512), nullable=True)
    uploaded_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    uploaded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)
    committed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    uploader = relationship("LegalOneUser", foreign_keys=[uploaded_by_user_id])
    eventos = relationship(
        "BaseProcessualEvento",
        back_populates="upload",
        cascade="all, delete-orphan",
        foreign_keys="BaseProcessualEvento.upload_id",
    )
    snapshots = relationship(
        "BaseProcessualSnapshot",
        back_populates="upload",
        cascade="all, delete-orphan",
        foreign_keys="BaseProcessualSnapshot.upload_id",
    )


class BaseProcessualProcesso(Base):
    __tablename__ = "base_processual_processo"

    id = Column(Integer, primary_key=True, index=True)
    cod_ajus = Column(String(64), nullable=False, unique=True, index=True)

    # Identificadores do processo
    numero_processo = Column(String(32), nullable=True, index=True)
    numero_processo_mascarado = Column(String(32), nullable=True)
    numero_interno = Column(String(128), nullable=True, index=True)
    numero_pasta = Column(String(128), nullable=True, index=True)

    # Atributos descritivos
    acao_principal = Column(String(512), nullable=True)
    materia = Column(String(128), nullable=True, index=True)
    risco_prob_perda = Column(String(64), nullable=True)
    tipo_acao = Column(String(256), nullable=True, index=True)
    polo = Column(String(32), nullable=True, index=True)
    natureza = Column(String(64), nullable=True, index=True)
    numero_vara = Column(String(64), nullable=True)
    foro = Column(String(256), nullable=True)
    comarca = Column(String(128), nullable=True, index=True)
    uf = Column(String(2), nullable=True, index=True)
    empresa = Column(String(128), nullable=False, index=True)

    # Responsaveis
    grupo_responsavel = Column(String(256), nullable=True)
    usuario_responsavel = Column(String(256), nullable=True, index=True)
    escritorio_responsavel = Column(String(256), nullable=True)

    situacao_processo = Column(
        String(64),
        nullable=False,
        default="Ativo",
        server_default="Ativo",
        index=True,
    )
    justica_honorario = Column(String(128), nullable=True)

    # Valores
    valor_causa = Column(Numeric(18, 2), nullable=True)
    valor_prev_acordo = Column(Numeric(18, 2), nullable=True)
    valor_acordo = Column(Numeric(18, 2), nullable=True)
    valor_discutido = Column(Numeric(18, 2), nullable=True)
    valor_exito = Column(Numeric(18, 2), nullable=True)
    valor_condenacao = Column(Numeric(18, 2), nullable=True)
    valor_contingencia = Column(Numeric(18, 2), nullable=True)

    # Andamentos
    ult_andamento = Column(Text, nullable=True)
    data_ult_andamento = Column(DateTime(timezone=True), nullable=True)
    dias_ult_atualizacao = Column(Integer, nullable=True)
    distribuido_em = Column(Date, nullable=True)
    processo_virtual = Column(Boolean, nullable=True)

    numero_contrato = Column(String(128), nullable=True)
    usuario_cadastro_acao = Column(String(256), nullable=True)
    data_cadastro_acao = Column(DateTime(timezone=True), nullable=True)

    # Partes (texto bruto + json parseado)
    autores_raw = Column(Text, nullable=True)
    reus_raw = Column(Text, nullable=True)
    autores_json = Column(JSON, nullable=True)
    reus_json = Column(JSON, nullable=True)

    # Presenca na base
    presenca_status = Column(
        String(32),
        nullable=False,
        default=PRESENCA_ATIVO,
        server_default=PRESENCA_ATIVO,
        index=True,
    )

    first_seen_upload_id = Column(
        Integer,
        ForeignKey("base_processual_upload.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_upload_id = Column(
        Integer,
        ForeignKey("base_processual_upload.id", ondelete="SET NULL"),
        nullable=True,
    )
    removed_at_upload_id = Column(
        Integer,
        ForeignKey("base_processual_upload.id", ondelete="SET NULL"),
        nullable=True,
    )
    # FK ciclica resolvida no alembic (use_alter na migration bp001).
    current_snapshot_id = Column(
        Integer,
        ForeignKey(
            "base_processual_snapshot.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_base_processual_processo_current_snapshot",
        ),
        nullable=True,
    )

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

    first_seen_upload = relationship(
        "BaseProcessualUpload", foreign_keys=[first_seen_upload_id]
    )
    last_seen_upload = relationship(
        "BaseProcessualUpload", foreign_keys=[last_seen_upload_id]
    )
    removed_at_upload = relationship(
        "BaseProcessualUpload", foreign_keys=[removed_at_upload_id]
    )
    current_snapshot = relationship(
        "BaseProcessualSnapshot", foreign_keys=[current_snapshot_id]
    )
    eventos = relationship(
        "BaseProcessualEvento",
        back_populates="processo",
        cascade="all, delete-orphan",
        foreign_keys="BaseProcessualEvento.processo_id",
    )
    snapshots = relationship(
        "BaseProcessualSnapshot",
        back_populates="processo",
        cascade="all, delete-orphan",
        foreign_keys="BaseProcessualSnapshot.processo_id",
    )


class BaseProcessualSnapshot(Base):
    __tablename__ = "base_processual_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "processo_id",
            "upload_id",
            name="uq_base_processual_snapshot_proc_upload",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    processo_id = Column(
        Integer,
        ForeignKey("base_processual_processo.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upload_id = Column(
        Integer,
        ForeignKey("base_processual_upload.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cod_ajus = Column(String(64), nullable=False, index=True)
    payload_normalized = Column(JSON, nullable=False)
    payload_raw = Column(JSON, nullable=True)
    diff_hash = Column(String(64), nullable=False, index=True)
    captured_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    processo = relationship(
        "BaseProcessualProcesso",
        foreign_keys=[processo_id],
        back_populates="snapshots",
    )
    upload = relationship(
        "BaseProcessualUpload",
        foreign_keys=[upload_id],
        back_populates="snapshots",
    )


class BaseProcessualEvento(Base):
    __tablename__ = "base_processual_evento"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(
        Integer,
        ForeignKey("base_processual_upload.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    processo_id = Column(
        Integer,
        ForeignKey("base_processual_processo.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cod_ajus = Column(String(64), nullable=False, index=True)
    tipo_evento = Column(String(32), nullable=False, index=True)
    changed_fields = Column(JSON, nullable=True)
    snapshot_before_id = Column(
        Integer,
        ForeignKey("base_processual_snapshot.id", ondelete="SET NULL"),
        nullable=True,
    )
    snapshot_after_id = Column(
        Integer,
        ForeignKey("base_processual_snapshot.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    upload = relationship(
        "BaseProcessualUpload", foreign_keys=[upload_id], back_populates="eventos"
    )
    processo = relationship(
        "BaseProcessualProcesso", foreign_keys=[processo_id], back_populates="eventos"
    )
    snapshot_before = relationship(
        "BaseProcessualSnapshot", foreign_keys=[snapshot_before_id]
    )
    snapshot_after = relationship(
        "BaseProcessualSnapshot", foreign_keys=[snapshot_after_id]
    )


class BaseProcessualApiKey(Base):
    __tablename__ = "base_processual_api_key"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(256), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(16), nullable=False)
    scope = Column(
        String(64),
        nullable=False,
        default="read_processos",
        server_default="read_processos",
    )
    rate_limit_per_min = Column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
