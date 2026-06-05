"""Models do modulo GED LegalOne — envio em lote de arquivos pro GED (ECM)
do Legal One a partir de CNJ + arquivo.

Dois modos de envio:
- SINGLE_FILE: um arquivo unico vai pra varios processos (CNJs). O arquivo
  e' guardado UMA vez (shared_file_*) e cada item aponta pro mesmo path.
- MULTI_FILE: varios arquivos, cada um mapeado a um CNJ (extraido do nome
  do arquivo ou corrigido a mao na UI).

Tabelas:
- GedUploadBatch: cabecalho do lote (modo, tipo no GED, status, contadores
  denormalizados, arquivo compartilhado no modo SINGLE_FILE).
- GedUploadItem: 1 row por (CNJ, arquivo). Status + ged_document_id por item.
  `ged_document_id != None` e' a CHAVE DE IDEMPOTENCIA: um item enviado com
  sucesso nunca e' re-enviado num retry/re-tick.

O worker (app/services/ged_legalone/upload_worker.py) pega itens PENDENTE
com lawsuit_id resolvido e chama legal_one_client.upload_document_to_ged.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


# ─── Modo do lote ─────────────────────────────────────────────────────
BATCH_MODE_SINGLE_FILE = "SINGLE_FILE"  # 1 arquivo -> N processos
BATCH_MODE_MULTI_FILE = "MULTI_FILE"    # N arquivos -> N processos

BATCH_MODES = frozenset({BATCH_MODE_SINGLE_FILE, BATCH_MODE_MULTI_FILE})

# ─── Status do lote ───────────────────────────────────────────────────
BATCH_STATUS_DRAFT = "DRAFT"
BATCH_STATUS_RESOLVING = "RESOLVING"          # resolvendo CNJ -> lawsuit_id
BATCH_STATUS_PROCESSING = "PROCESSING"        # worker subindo itens
BATCH_STATUS_DONE = "DONE"                    # todos os itens OK
BATCH_STATUS_DONE_WITH_ERRORS = "DONE_WITH_ERRORS"
BATCH_STATUS_CANCELLED = "CANCELLED"

BATCH_TERMINAL_STATUSES = frozenset({
    BATCH_STATUS_DONE,
    BATCH_STATUS_DONE_WITH_ERRORS,
    BATCH_STATUS_CANCELLED,
})

# ─── Status do item ───────────────────────────────────────────────────
ITEM_STATUS_PENDENTE = "PENDENTE"
ITEM_STATUS_PROCESSANDO = "PROCESSANDO"
ITEM_STATUS_SUCESSO = "SUCESSO"
ITEM_STATUS_ERRO = "ERRO"
ITEM_STATUS_CNJ_NAO_ENCONTRADO = "CNJ_NAO_ENCONTRADO"

# Status que contam como "falha re-enfileiravel" no retry-failed.
ITEM_RETRYABLE_STATUSES = frozenset({
    ITEM_STATUS_ERRO,
    ITEM_STATUS_CNJ_NAO_ENCONTRADO,
})


class GedUploadBatch(Base):
    """Cabecalho de 1 lote de envio ao GED."""

    __tablename__ = "ged_upload_batch"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    mode = Column(String(16), nullable=False)
    # typeId do GED no formato "type_N" (ex.: "type_48" = Habilitacao) ou
    # None = sem tipo (operador define no L1 depois).
    type_id = Column(String(16), nullable=True)
    description = Column(Text, nullable=True)

    status = Column(
        String(24),
        nullable=False,
        default=BATCH_STATUS_DRAFT,
        server_default=BATCH_STATUS_DRAFT,
        index=True,
    )

    # Contadores denormalizados — recomputados a cada resolve/tick a partir
    # dos itens (fonte da verdade sao os itens; isso e' cache pra UI/listagem).
    total_itens = Column(Integer, nullable=False, default=0, server_default="0")
    total_sucesso = Column(Integer, nullable=False, default=0, server_default="0")
    total_erro = Column(Integer, nullable=False, default=0, server_default="0")
    total_pendente = Column(Integer, nullable=False, default=0, server_default="0")

    # Modo SINGLE_FILE: o arquivo unico, guardado 1x no volume. NULL no
    # MULTI_FILE (cada item tem seu proprio file_path).
    shared_file_path = Column(String(512), nullable=True)
    shared_file_sha256 = Column(String(64), nullable=True)
    shared_original_filename = Column(String(255), nullable=True)

    error_message = Column(Text, nullable=True)

    created_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    resolving_started_at = Column(DateTime(timezone=True), nullable=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    itens = relationship(
        "GedUploadItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class GedUploadItem(Base):
    """1 envio (CNJ + arquivo) dentro de um lote."""

    __tablename__ = "ged_upload_item"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(
        Integer,
        ForeignKey("ged_upload_batch.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # CNJ normalizado (20 digitos, sem mascara). NULL quando o operador
    # subiu um arquivo sem CNJ (modo MULTI_FILE com nome sem CNJ e sem override).
    cnj_number = Column(String(64), nullable=True, index=True)
    # litigation id resolvido no L1 (search_lawsuits_by_cnj_numbers). NULL
    # ate resolver; se nao achar, item vira CNJ_NAO_ENCONTRADO.
    lawsuit_id = Column(Integer, nullable=True)

    # Arquivo no volume. No modo SINGLE_FILE todos os itens apontam pro
    # MESMO path (= batch.shared_file_path), denormalizado pra o worker
    # ler de forma uniforme nos dois modos.
    file_path = Column(String(512), nullable=True)
    original_filename = Column(String(255), nullable=True)
    file_ext = Column(String(16), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    sha256 = Column(String(64), nullable=True, index=True)

    status = Column(
        String(24),
        nullable=False,
        default=ITEM_STATUS_PENDENTE,
        server_default=ITEM_STATUS_PENDENTE,
        index=True,
    )
    # ID do documento criado no GED. != None => enviado com sucesso. E' a
    # chave de idempotencia: o worker NUNCA re-sobe um item com isso setado.
    ged_document_id = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    batch = relationship("GedUploadBatch", back_populates="itens")

    __table_args__ = (
        # Query quente do worker: itens PENDENTE de um batch / contadores.
        Index("ix_ged_upload_item_batch_status", "batch_id", "status"),
    )
