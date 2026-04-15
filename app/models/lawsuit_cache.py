"""
Cache local de lookups de processos no Legal One.

Cada chamada a /Lawsuits ou /Litigations por ID consome quota da Firm Premium
(90 req/min, 130k/dia, 300k/mês). Como a informação requerida
(responsibleOfficeId + identifierNumber) é estável no curto prazo, cacheamos
localmente por 24h — reduz drasticamente o consumo quando a mesma pasta
recebe múltiplas publicações.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, JSON
from sqlalchemy.sql import func

from app.db.session import Base


LAWSUIT_CACHE_TTL = timedelta(hours=24)


class LawsuitCache(Base):
    __tablename__ = "lawsuit_cache"

    lawsuit_id = Column(Integer, primary_key=True, index=True)
    payload = Column(JSON, nullable=False)  # {id, identifierNumber, responsibleOfficeId, ...}
    fetched_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def is_fresh(self, ttl: timedelta = LAWSUIT_CACHE_TTL) -> bool:
        if self.fetched_at is None:
            return False
        now = datetime.now(timezone.utc)
        fetched = self.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return (now - fetched) < ttl
