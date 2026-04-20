"""
Fila de cancelamento da task legada de "Agendar Prazos" em Prazos Iniciais.

Esta fila separa:
- o status de negocio do intake (AGENDADO = o operador confirmou os
  agendamentos do processo)
- o status tecnico do RPA que precisa entrar no Legal One e cancelar a
  task legado que ficou obsoleta para aquele mesmo processo.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from app.db.session import Base


QUEUE_STATUS_PENDING = "PENDENTE"
QUEUE_STATUS_PROCESSING = "PROCESSANDO"
QUEUE_STATUS_COMPLETED = "CONCLUIDO"
QUEUE_STATUS_FAILED = "FALHA"
QUEUE_STATUS_CANCELLED = "CANCELADO"

VALID_QUEUE_STATUSES = {
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_CANCELLED,
}


class PrazoInicialLegacyTaskCancellationItem(Base):
    __tablename__ = "prazo_inicial_legacy_task_cancel_items"

    id = Column(Integer, primary_key=True, index=True)
    intake_id = Column(
        Integer,
        ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    lawsuit_id = Column(Integer, nullable=True, index=True)
    cnj_number = Column(String(32), nullable=True, index=True)
    office_id = Column(Integer, nullable=True, index=True)

    legacy_task_type_external_id = Column(Integer, nullable=False, default=33)
    legacy_task_subtype_external_id = Column(Integer, nullable=False, default=1283)

    queue_status = Column(String(24), nullable=False, default=QUEUE_STATUS_PENDING, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)

    selected_task_id = Column(Integer, nullable=True, index=True)
    cancelled_task_id = Column(Integer, nullable=True, index=True)
    last_reason = Column(String(64), nullable=True, index=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    last_result = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    intake = relationship(
        "PrazoInicialIntake",
        backref=backref("legacy_task_cancellation_item", uselist=False),
    )
