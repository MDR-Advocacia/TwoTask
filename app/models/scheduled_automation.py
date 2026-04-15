"""
Modelo para agendamentos de automação (ex: puxar publicações + classificar).

Permite que operadores configurem jobs recorrentes que rodam em background.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class ScheduledAutomation(Base):
    """
    Define um agendamento automático de tarefas.

    Exemplos:
    - "Diário 07:00 - Puxar + Classificar SP"
    - "A cada 6 horas - Puxar publicações RJ"
    """

    __tablename__ = "scheduled_automations"

    id = Column(Integer, primary_key=True, index=True)

    # Metadata
    name = Column(String, nullable=False)
    created_by = Column(Integer, ForeignKey("legal_one_users.id"), nullable=True)
    is_enabled = Column(Boolean, default=True, nullable=False)

    # Scheduling: either cron_expression OR interval_minutes
    # cron_expression example: "0 7 * * *" (daily at 7am)
    # interval_minutes example: 360 (every 6 hours)
    cron_expression = Column(String, nullable=True)
    interval_minutes = Column(Integer, nullable=True)

    # Configuration
    office_ids = Column(JSON, nullable=False)  # List of office external_ids
    # steps: ["pull_publications", "classify"]
    steps = Column(JSON, nullable=False)

    # Janela de busca (por automação — sobrepõe os defaults globais)
    # Dias que a 1ª rodagem (sem cursor) olha para trás.
    initial_lookback_days = Column(Integer, nullable=True)
    # Horas de overlap defensivo aplicadas às rodagens recorrentes.
    overlap_hours = Column(Integer, nullable=True)

    # Execution tracking
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String, nullable=True)  # "success", "failed", etc.
    last_error = Column(Text, nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    runs = relationship("ScheduledAutomationRun", back_populates="automation", cascade="all, delete-orphan")
    creator = relationship("LegalOneUser", foreign_keys=[created_by])


class ScheduledAutomationRun(Base):
    """
    Log de cada execução de um agendamento.
    """

    __tablename__ = "scheduled_automation_runs"

    id = Column(Integer, primary_key=True, index=True)

    automation_id = Column(Integer, ForeignKey("scheduled_automations.id", ondelete="CASCADE"), nullable=False, index=True)

    # Execution details
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    status = Column(String, nullable=False)  # "running", "success", "failed"
    error_message = Column(Text, nullable=True)

    # Summary (from completed steps)
    steps_executed = Column(JSON, nullable=True)  # [{"step": "pull_publications", "status": "success", "records_found": 10}, ...]

    # Progress tracking (atualizado ao longo da execução)
    progress_phase = Column(String, nullable=True)     # ex: "pull_publications:fetch"
    progress_current = Column(Integer, nullable=True)  # ex: 120
    progress_total = Column(Integer, nullable=True)    # ex: 1024
    progress_message = Column(String, nullable=True)   # ex: "Buscando publicações (120/1024)"
    progress_updated_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    automation = relationship("ScheduledAutomation", back_populates="runs")
