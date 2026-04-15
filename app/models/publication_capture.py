"""
Models para rastreamento confiável de captura de publicações do Legal One.

- OfficePublicationCursor: watermark por escritório (até onde já capturamos com sucesso).
- PublicationFetchAttempt: histórico de tentativas de fetch por janela, para retry e dead-letter.
"""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text, func, Index

from app.db.session import Base


# Status possíveis
CURSOR_STATUS_OK = "ok"
CURSOR_STATUS_FAILED = "failed"
CURSOR_STATUS_DEAD_LETTER = "dead_letter"

ATTEMPT_STATUS_PENDING = "pending"
ATTEMPT_STATUS_SUCCESS = "success"
ATTEMPT_STATUS_FAILED = "failed"
ATTEMPT_STATUS_DEAD_LETTER = "dead_letter"

# Backoff em minutos: 1, 5, 30, 60 — após 4 falhas vai para dead_letter
RETRY_BACKOFF_MINUTES = [1, 5, 30, 60]
MAX_CONSECUTIVE_FAILURES_BEFORE_DEAD_LETTER = len(RETRY_BACKOFF_MINUTES)


class OfficePublicationCursor(Base):
    __tablename__ = "office_publication_cursor"

    office_id = Column(Integer, primary_key=True)
    last_successful_date = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PublicationFetchAttempt(Base):
    __tablename__ = "publication_fetch_attempt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    office_id = Column(Integer, nullable=False, index=True)
    window_from = Column(DateTime(timezone=True), nullable=False)
    window_to = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False)
    attempt_n = Column(Integer, nullable=False, default=1)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    records_found = Column(Integer, nullable=True)
    automation_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


Index("ix_pfa_status_next_retry", PublicationFetchAttempt.status, PublicationFetchAttempt.next_retry_at)
