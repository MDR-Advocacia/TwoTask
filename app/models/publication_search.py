"""
Models para o motor de busca de publicações do Legal One.

PublicationSearch  → Registro de cada busca disparada (com filtros usados)
PublicationRecord  → Cada publicação encontrada e seu status de processamento
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base

SEARCH_STATUS_PENDING = "PENDENTE"
SEARCH_STATUS_RUNNING = "EXECUTANDO"
SEARCH_STATUS_COMPLETED = "CONCLUIDO"
SEARCH_STATUS_FAILED = "FALHA"
SEARCH_STATUS_CANCELLED = "CANCELADO"

RECORD_STATUS_NEW = "NOVO"
RECORD_STATUS_CLASSIFIED = "CLASSIFICADO"
RECORD_STATUS_SCHEDULED = "AGENDADO"
RECORD_STATUS_IGNORED = "IGNORADO"
RECORD_STATUS_ERROR = "ERRO"
# Descartada por duplicidade de (lawsuit_id, publication_date) —
# uma mesma publicação para um mesmo processo no mesmo dia é tratada
# apenas uma vez, economizando tokens de classificação e chamadas à API do L1.
RECORD_STATUS_DISCARDED_DUPLICATE = "DESCARTADO_DUPLICADA"
# Publicação anterior à data de criação da pasta do processo no Legal One —
# já auditada na esteira processual de admissão, sem providência necessária.
RECORD_STATUS_OBSOLETE = "DESCARTADO_OBSOLETA"

# Polo da publicação (a qual lado do processo a publicação se refere)
POLO_ATIVO = "ativo"
POLO_PASSIVO = "passivo"
POLO_AMBOS = "ambos"
VALID_POLOS = {POLO_ATIVO, POLO_PASSIVO, POLO_AMBOS}


class PublicationSearch(Base):
    __tablename__ = "publicacao_buscas"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default=SEARCH_STATUS_PENDING, index=True)

    # Filtros usados na busca (rastreabilidade)
    date_from = Column(String, nullable=False)
    date_to = Column(String, nullable=True)
    origin_type = Column(String, nullable=False, default="OfficialJournalsCrawler")
    office_filter = Column(String, nullable=True)

    # Resultados
    total_found = Column(Integer, default=0)
    total_new = Column(Integer, default=0)
    total_duplicate = Column(Integer, default=0)

    # Metadados
    requested_by_email = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(String, nullable=True)

    records = relationship(
        "PublicationRecord",
        back_populates="search",
        cascade="all, delete-orphan",
    )


class PublicationRecord(Base):
    __tablename__ = "publicacao_registros"

    id = Column(Integer, primary_key=True, index=True)
    search_id = Column(Integer, ForeignKey("publicacao_buscas.id"), nullable=False)

    # Dados da publicação do Legal One
    legal_one_update_id = Column(Integer, nullable=False, index=True, unique=True)
    origin_type = Column(String, nullable=True)
    update_type_id = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    publication_date = Column(String, nullable=True)
    creation_date = Column(String, nullable=True)

    # Vínculos (relationships do Legal One)
    linked_lawsuit_id = Column(Integer, nullable=True, index=True)
    linked_lawsuit_cnj = Column(String, nullable=True, index=True)
    linked_office_id = Column(Integer, nullable=True)
    raw_relationships = Column(JSON, nullable=True)

    # Status de processamento
    status = Column(String, nullable=False, default=RECORD_STATUS_NEW, index=True)
    is_duplicate = Column(Boolean, default=False)

    # Vínculo com classificação (preenchido quando classificado)
    classification_item_id = Column(Integer, nullable=True)
    category = Column(String, nullable=True)
    subcategory = Column(String, nullable=True)
    # Polo da publicação: "ativo", "passivo" ou "ambos"
    polo = Column(String, nullable=True, index=True)
    # Data/hora da audiência extraída pelo classificador (ISO: "YYYY-MM-DD" / "HH:MM")
    audiencia_data = Column(String, nullable=True)
    audiencia_hora = Column(String, nullable=True)
    # Link de audiência virtual (videoconferência) extraído do texto
    audiencia_link = Column(String, nullable=True)
    # Múltiplas classificações (JSON array quando a publicação tem mais de uma)
    # [{categoria, subcategoria, polo, audiencia_data, audiencia_hora, audiencia_link, confianca, justificativa}]
    classifications = Column(JSON, nullable=True)

    # UF/região derivada do CNJ (materializada para filtro SQL eficiente).
    # Ex.: "SP", "RJ", "TRT7", "TRF1", "TRE-SP". Populada automaticamente
    # ao criar o registro e pela data migration perf002.
    uf = Column(String(10), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    search = relationship("PublicationSearch", back_populates="records")
    treatment_item = relationship(
        "PublicationTreatmentItem",
        back_populates="record",
        uselist=False,
    )
