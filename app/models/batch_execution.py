from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.db.session import Base

BATCH_STATUS_PENDING = "PENDENTE"
BATCH_STATUS_PROCESSING = "PROCESSANDO"
BATCH_STATUS_PAUSED = "PAUSADO"
BATCH_STATUS_CANCELLED = "CANCELADO"
BATCH_STATUS_COMPLETED = "CONCLUIDO"
BATCH_STATUS_COMPLETED_WITH_ERRORS = "CONCLUIDO_COM_FALHAS"

BATCH_PROCESSOR_GENERIC = "GENERIC"
BATCH_PROCESSOR_SPREADSHEET_UPLOAD = "SPREADSHEET_UPLOAD"
BATCH_PROCESSOR_SPREADSHEET_INTERACTIVE = "SPREADSHEET_INTERACTIVE"

FINAL_BATCH_STATUSES = {
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_COMPLETED,
    BATCH_STATUS_COMPLETED_WITH_ERRORS,
}

QUEUEABLE_BATCH_PROCESSORS = {
    BATCH_PROCESSOR_SPREADSHEET_UPLOAD,
    BATCH_PROCESSOR_SPREADSHEET_INTERACTIVE,
}


class BatchExecution(Base):
    __tablename__ = "lotes_execucao"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False, index=True)
    processor_type = Column(String, nullable=False, default=BATCH_PROCESSOR_GENERIC, index=True)
    source_filename = Column(String, nullable=True)
    requested_by_email = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default=BATCH_STATUS_PENDING, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    total_items = Column(Integer, nullable=False)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    worker_id = Column(String, nullable=True, index=True)

    items = relationship(
        "BatchExecutionItem",
        back_populates="execution",
        cascade="all, delete-orphan",
    )


class BatchExecutionItem(Base):
    __tablename__ = "lotes_itens"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("lotes_execucao.id"), nullable=False)
    process_number = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    created_task_id = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)
    fingerprint = Column(String, nullable=True, index=True)
    input_data = Column(JSON, nullable=True)

    execution = relationship("BatchExecution", back_populates="items")
