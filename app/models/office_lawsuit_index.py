"""
Índice persistente de processos por escritório responsável.

Permite pré-filtrar publicações antes do enriquecimento (que é a parte
cara do fluxo de busca). Atualizado via sync on-demand ou incremental.

- office_lawsuit_index: linhas (office_id, lawsuit_id) + last_seen_at
- office_lawsuit_sync: metadados de sincronização por escritório
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func, false, true

from app.db.session import Base


class OfficeLawsuitIndex(Base):
    __tablename__ = "office_lawsuit_index"

    office_id = Column(Integer, primary_key=True, index=True)
    lawsuit_id = Column(Integer, primary_key=True, index=True)
    last_seen_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class OfficeLawsuitSync(Base):
    __tablename__ = "office_lawsuit_sync"

    office_id = Column(Integer, primary_key=True)
    last_full_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_incremental_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_status = Column(String(32), nullable=True)  # running/success/error
    last_sync_error = Column(Text, nullable=True)
    total_ids = Column(Integer, nullable=False, server_default="0", default=0)
    in_progress = Column(Boolean, nullable=False, server_default=false(), default=False)
    progress_pct = Column(Integer, nullable=False, server_default="0", default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    supports_incremental = Column(
        Boolean, nullable=False, server_default=true(), default=True
    )
