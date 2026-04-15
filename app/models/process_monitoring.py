import sqlalchemy as sa
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class MonitoringPortfolio(Base):
    __tablename__ = "monitoring_portfolios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    client_name = Column(String, nullable=False, index=True)
    business_unit = Column(String, nullable=True, index=True)
    operation_name = Column(String, nullable=True, index=True)
    segment = Column(String, nullable=True, index=True)
    monitoring_parameters = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())

    processes = relationship("MonitoredProcess", back_populates="portfolio", cascade="all, delete-orphan")


class MonitoredProcess(Base):
    __tablename__ = "monitored_processes"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "normalized_process_number", name="uq_monitored_process_portfolio_number"),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("monitoring_portfolios.id"), nullable=False, index=True)

    process_number = Column(String, nullable=False, index=True)
    normalized_process_number = Column(String, nullable=False, index=True)
    tribunal = Column(String, nullable=True, index=True)
    tribunal_alias = Column(String, nullable=True, index=True)
    instance_level = Column(String, nullable=True, index=True)
    procedural_class = Column(String, nullable=True, index=True)
    judging_body = Column(String, nullable=True, index=True)
    system_name = Column(String, nullable=True)
    secrecy_level = Column(Integer, nullable=True)
    filed_at = Column(Date, nullable=True)
    last_datajud_update_at = Column(DateTime(timezone=True), nullable=True, index=True)
    indexed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_datajud_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_publication_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_classified_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_relevant_event_at = Column(DateTime(timezone=True), nullable=True, index=True)
    analytical_status = Column(String, nullable=False, default="MONITORED", index=True)
    maturity_level = Column(Integer, nullable=False, default=0, index=True)
    current_score = Column(Float, nullable=False, default=0)
    queue_name = Column(String, nullable=True, index=True)
    monitoring_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())

    portfolio = relationship("MonitoringPortfolio", back_populates="processes")
    raw_payloads = relationship("ProcessRawPayload", back_populates="monitored_process", cascade="all, delete-orphan")
    movements = relationship("ProcessMovement", back_populates="monitored_process", cascade="all, delete-orphan")
    publications = relationship("ProcessPublication", back_populates="monitored_process", cascade="all, delete-orphan")
    analytical_events = relationship("ProcessAnalyticalEvent", back_populates="monitored_process", cascade="all, delete-orphan")
    queue_items = relationship("ProcessOperationalQueueItem", back_populates="monitored_process", cascade="all, delete-orphan")


class ProcessRawPayload(Base):
    __tablename__ = "process_raw_payloads"

    id = Column(Integer, primary_key=True, index=True)
    monitored_process_id = Column(Integer, ForeignKey("monitored_processes.id"), nullable=True, index=True)
    source = Column(String, nullable=False, index=True)
    external_reference = Column(String, nullable=True, index=True)
    tribunal = Column(String, nullable=True, index=True)
    process_number = Column(String, nullable=True, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String, nullable=True, index=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True)

    monitored_process = relationship("MonitoredProcess", back_populates="raw_payloads")


class ProcessMovement(Base):
    __tablename__ = "process_movements"

    id = Column(Integer, primary_key=True, index=True)
    monitored_process_id = Column(Integer, ForeignKey("monitored_processes.id"), nullable=False, index=True)
    movement_code = Column(String, nullable=True, index=True)
    movement_name = Column(String, nullable=False, index=True)
    movement_at = Column(DateTime(timezone=True), nullable=True, index=True)
    judging_body = Column(String, nullable=True, index=True)
    complements = Column(JSON, nullable=False, default=dict)
    raw_payload = Column(JSON, nullable=False, default=dict)
    is_decision_event = Column(Boolean, nullable=False, default=False, index=True)
    is_recursal_signal = Column(Boolean, nullable=False, default=False, index=True)
    is_transit_signal = Column(Boolean, nullable=False, default=False, index=True)
    is_closure_signal = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())

    monitored_process = relationship("MonitoredProcess", back_populates="movements")


class ProcessPublication(Base):
    __tablename__ = "process_publications"

    id = Column(Integer, primary_key=True, index=True)
    monitored_process_id = Column(Integer, ForeignKey("monitored_processes.id"), nullable=True, index=True)
    source = Column(String, nullable=False, index=True)
    communication_hash = Column(String, nullable=True, index=True)
    certificate_hash = Column(String, nullable=True, index=True)
    publication_date = Column(Date, nullable=True, index=True)
    publication_datetime = Column(DateTime(timezone=True), nullable=True, index=True)
    medium = Column(String, nullable=True, index=True)
    tribunal = Column(String, nullable=True, index=True)
    process_number = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    publication_text = Column(Text, nullable=True)
    certificate_url = Column(String, nullable=True)
    publication_metadata = Column("metadata", JSON, nullable=False, default=dict)
    correlation_confidence = Column(Float, nullable=False, default=0)
    is_decision_publication = Column(Boolean, nullable=False, default=False, index=True)
    is_transit_signal = Column(Boolean, nullable=False, default=False, index=True)
    is_closure_signal = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())

    monitored_process = relationship("MonitoredProcess", back_populates="publications")


class ProcessAnalyticalEvent(Base):
    __tablename__ = "process_analytical_events"

    id = Column(Integer, primary_key=True, index=True)
    monitored_process_id = Column(Integer, ForeignKey("monitored_processes.id"), nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    rule_code = Column(String, nullable=False, index=True)
    rule_version = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    event_time = Column(DateTime(timezone=True), nullable=True, index=True)
    score_impact = Column(Float, nullable=False, default=0)
    confidence = Column(Float, nullable=False, default=0)
    maturity_level_after = Column(Integer, nullable=False, default=0, index=True)
    analytical_status_after = Column(String, nullable=False, index=True)
    suggested_action = Column(String, nullable=True)
    justification = Column(Text, nullable=False)
    evidence = Column(JSON, nullable=False, default=dict)
    homologation_status = Column(String, nullable=False, default="PENDING_REVIEW", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True)

    monitored_process = relationship("MonitoredProcess", back_populates="analytical_events")


class ProcessOperationalQueueItem(Base):
    __tablename__ = "process_operational_queue_items"

    id = Column(Integer, primary_key=True, index=True)
    monitored_process_id = Column(Integer, ForeignKey("monitored_processes.id"), nullable=False, index=True)
    queue_name = Column(String, nullable=False, index=True)
    priority = Column(String, nullable=False, default="MEDIUM", index=True)
    status = Column(String, nullable=False, default="PENDING_REVIEW", index=True)
    suggested_action = Column(String, nullable=False)
    score = Column(Float, nullable=False, default=0, index=True)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    opened_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String, nullable=True)

    monitored_process = relationship("MonitoredProcess", back_populates="queue_items")


class IntegrationSyncRun(Base):
    __tablename__ = "integration_sync_runs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False, index=True)
    tribunal = Column(String, nullable=True, index=True)
    scope = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="PENDING", index=True)
    request_payload = Column(JSON, nullable=False, default=dict)
    response_metadata = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True, index=True)


class IntegrationSyncCursor(Base):
    __tablename__ = "integration_sync_cursors"
    __table_args__ = (
        UniqueConstraint("source", "tribunal", "cursor_key", name="uq_integration_cursor_scope"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False, index=True)
    tribunal = Column(String, nullable=True, index=True)
    cursor_key = Column(String, nullable=False, index=True)
    cursor_value = Column(JSON, nullable=False, default=list)
    last_synced_at = Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True)
    cursor_metadata = Column("metadata", JSON, nullable=False, default=dict)
