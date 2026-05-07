"""Modelo SQLAlchemy pra a tabela app_settings (key/value).

Tabela criada por tax008. Usada inicialmente pra o toggle global
`taxonomy_active_version` (v1/v2), mas pode receber outros settings
admin no futuro.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
