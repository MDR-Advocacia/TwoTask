from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base

CLF_STATUS_PENDING = "PENDENTE"
CLF_STATUS_PROCESSING = "PROCESSANDO"
CLF_STATUS_COMPLETED = "CONCLUIDO"
CLF_STATUS_COMPLETED_WITH_ERRORS = "CONCLUIDO_COM_FALHAS"
CLF_STATUS_CANCELLED = "CANCELADO"

CLF_ITEM_PENDING = "PENDENTE"
CLF_ITEM_SUCCESS = "SUCESSO"
CLF_ITEM_FAILED = "FALHA"

FINAL_CLF_STATUSES = {
    CLF_STATUS_COMPLETED,
    CLF_STATUS_COMPLETED_WITH_ERRORS,
    CLF_STATUS_CANCELLED,
}


class ClassificationBatch(Base):
    __tablename__ = "classificacao_lotes"

    id = Column(Integer, primary_key=True, index=True)
    source_filename = Column(String, nullable=True)
    requested_by_email = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default=CLF_STATUS_PENDING, index=True)
    model_used = Column(String, nullable=True)
    total_items = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship(
        "ClassificationItem",
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class ClassificationItem(Base):
    __tablename__ = "classificacao_itens"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("classificacao_lotes.id"), nullable=False)
    row_index = Column(Integer, nullable=False)
    process_number = Column(String, nullable=False, index=True)
    publication_text = Column(Text, nullable=True)
    status = Column(String, nullable=False, default=CLF_ITEM_PENDING)

    # Resultado da classificação
    category = Column(String, nullable=True)
    subcategory = Column(String, nullable=True)
    confidence = Column(String, nullable=True)
    justification = Column(String, nullable=True)

    error_message = Column(String, nullable=True)
    raw_response = Column(JSON, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    batch = relationship("ClassificationBatch", back_populates="items")
