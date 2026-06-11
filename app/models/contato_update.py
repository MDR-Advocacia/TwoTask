"""Models do modulo Atualizacao de Contatos LegalOne — enriquece contatos
ja' existentes no Legal One (achados pelo CPF/CNPJ) com telefones, e-mail e
endereco vindos de um CSV (Dossie com CPF e CNPJ).

Fluxo (ver docs ESTUDO-API-CONTATOS-LEGALONE.md):
- O operador sobe um CSV. Cada linha vira 1 item.
- O worker (enrich_worker.py), item a item: acha o contato pelo
  identificationNumber (CPF -> /Individuals, CNPJ -> /Companies), le' as
  colecoes existentes (idempotencia) e faz POST nas navigation properties
  phones/emails/addresses apenas do que falta.
- `dry_run=True`: o worker simula (le' + monta o plano) e grava em
  result_json o que SERIA enviado, sem escrever nada no L1.

Idempotencia: cada execucao le' os existentes antes de cada POST e so' cria
o que falta (normaliza telefone por digitos, e-mail por lower, endereco por
linha+numero+cidade). Reexecutar um lote nao duplica.

Tabelas:
- ContatoAtualizacaoBatch: cabecalho do lote (status, dry_run, contadores
  denormalizados, metadados do arquivo).
- ContatoAtualizacaoItem: 1 linha do CSV. Guarda o payload parseado
  (payload_json), o id do contato resolvido e o relatorio do que foi
  criado/pulado (result_json).
"""

from sqlalchemy import (
    JSON,
    Boolean,
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


# ─── Status do lote ───────────────────────────────────────────────────
BATCH_STATUS_PROCESSING = "PROCESSING"          # worker enriquecendo itens
BATCH_STATUS_DONE = "DONE"                       # todos os itens OK
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
ITEM_STATUS_SUCESSO = "SUCESSO"            # gravou (ou ja' estava tudo la')
ITEM_STATUS_ERRO = "ERRO"                  # falha tecnica (400/timeout/etc.)
ITEM_STATUS_NAO_ENCONTRADO = "NAO_ENCONTRADO"  # CPF/CNPJ sem contato no L1
ITEM_STATUS_DUPLICADO = "DUPLICADO"        # >1 contato com o mesmo doc no L1

# Doc kinds
DOC_KIND_CPF = "CPF"
DOC_KIND_CNPJ = "CNPJ"

# Status que contam como "falha re-enfileiravel" no retry-failed.
ITEM_RETRYABLE_STATUSES = frozenset({
    ITEM_STATUS_ERRO,
    ITEM_STATUS_NAO_ENCONTRADO,
})


class ContatoAtualizacaoBatch(Base):
    """Cabecalho de 1 lote de atualizacao de contatos."""

    __tablename__ = "contato_atualizacao_batch"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # dry_run: worker simula (le' + monta plano) sem POST no L1. Default True
    # — escrita real exige decisao explicita do operador (LGPD / producao).
    dry_run = Column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    status = Column(
        String(24),
        nullable=False,
        default=BATCH_STATUS_PROCESSING,
        server_default=BATCH_STATUS_PROCESSING,
        index=True,
    )

    # Contadores denormalizados — recomputados a cada tick a partir dos itens
    # (fonte da verdade sao os itens; isso e' cache pra UI/listagem).
    total_itens = Column(Integer, nullable=False, default=0, server_default="0")
    total_sucesso = Column(Integer, nullable=False, default=0, server_default="0")
    total_erro = Column(Integer, nullable=False, default=0, server_default="0")
    total_pendente = Column(Integer, nullable=False, default=0, server_default="0")

    # Metadados do arquivo (o CSV cru NAO e' persistido — PII/LGPD; guardamos
    # so' o nome e o hash pra rastreio).
    source_filename = Column(String(255), nullable=True)
    source_sha256 = Column(String(64), nullable=True)

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
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    itens = relationship(
        "ContatoAtualizacaoItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ContatoAtualizacaoItem(Base):
    """1 linha do CSV dentro de um lote de atualizacao."""

    __tablename__ = "contato_atualizacao_item"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(
        Integer,
        ForeignKey("contato_atualizacao_batch.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Numero da linha no CSV (1-based, sem contar o cabecalho) — pro relatorio.
    row_number = Column(Integer, nullable=True)

    # Documento como veio no CSV (com mascara — e' o formato que o L1 guarda
    # em identificationNumber e o que a busca casa). doc_digits = so' digitos.
    doc_number = Column(String(32), nullable=False, index=True)
    doc_digits = Column(String(20), nullable=True, index=True)
    doc_kind = Column(String(8), nullable=False)  # CPF | CNPJ

    nome_abreviado = Column(String(255), nullable=True)  # metadado da campanha

    # Payload parseado da linha: { phones: [...], email: {...}|None,
    # address: {...}|None }. O worker le' daqui (nao re-parseia o CSV).
    payload_json = Column(JSON, nullable=True)

    # id do contato resolvido no L1 (/Individuals ou /Companies). NULL ate'
    # achar; se nao achar, item vira NAO_ENCONTRADO.
    contact_id = Column(Integer, nullable=True)

    status = Column(
        String(24),
        nullable=False,
        default=ITEM_STATUS_PENDENTE,
        server_default=ITEM_STATUS_PENDENTE,
        index=True,
    )
    # Relatorio por item: { created: {phones, emails, addresses}, skipped: [...],
    # errors: [...], city_id, contact_id, dry_run }. Fonte do detalhe na UI.
    result_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    batch = relationship("ContatoAtualizacaoBatch", back_populates="itens")

    __table_args__ = (
        # Query quente do worker: itens PENDENTE de um batch / contadores.
        Index("ix_contato_atualizacao_item_batch_status", "batch_id", "status"),
    )
