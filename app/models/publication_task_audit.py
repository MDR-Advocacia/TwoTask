"""Auditoria de agendamento de tarefas de Publicações.

Grava, por TAREFA criada no Legal One, o payload EXATO que foi enviado +
quem agendou + a proposta automática + o diff entre as duas (flag de override
humano). Motivação: o L1 registra o criador como "Sistema" (usuário da API),
então só o Flow consegue dizer QUEM (operador) agendou/modificou e SE divergiu
da sugestão automática. Append-only — nunca atualiza/deleta.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.session import Base


class PublicationTaskAudit(Base):
    __tablename__ = "publicacao_tarefa_audit"

    id = Column(Integer, primary_key=True, index=True)

    lawsuit_id = Column(Integer, nullable=True, index=True)  # None no fluxo avulso
    publication_record_id = Column(Integer, nullable=True, index=True)
    subtype_id = Column(Integer, nullable=True)
    created_task_id = Column(Integer, nullable=True, index=True)

    # O que foi REALMENTE enviado ao L1 (após override do operador + squad
    # routing + defaults) e a proposta automática original, pra comparação.
    sent_payload = Column(JSONB, nullable=True)
    proposed_payload = Column(JSONB, nullable=True)

    # True quando o enviado divergiu da proposta em subtipo/escritório/responsável.
    override_detected = Column(Boolean, nullable=False, server_default="false", index=True)
    override_fields = Column(JSONB, nullable=True)  # {campo: {proposto, enviado}}

    # Quem agendou (snapshot do operador — o L1 só guarda "Sistema").
    scheduled_by_user_id = Column(Integer, nullable=True, index=True)
    scheduled_by_name = Column(String, nullable=True)
    scheduled_by_email = Column(String, nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
