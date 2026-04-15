"""
Template de tarefa para o motor de agendamento automático de publicações.

Cada template define, para uma combinação de (category, subcategory, office),
qual tipo/subtipo de tarefa será criado no Legal One, qual usuário será
responsável, prioridade, prazo em dias úteis e o corpo da descrição/notas.

O motor de proposta usa estes templates para pré-montar o payload que o
operador revisa e confirma antes de enviar ao Legal One.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class TaskTemplate(Base):
    __tablename__ = "task_templates"
    # Múltiplos templates por (category, subcategory, office) são permitidos,
    # cada um gera uma tarefa diferente no agendamento.
    __table_args__ = ()

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # Critério de casamento (classificação + escritório responsável)
    # office_external_id = NULL → template "global": aplica a publicações sem escritório vinculado
    category = Column(String, nullable=False, index=True)
    subcategory = Column(String, nullable=True, index=True)
    office_external_id = Column(
        Integer,
        ForeignKey("legal_one_offices.external_id"),
        nullable=True,   # NULL = template para publicações sem processo/escritório
        index=True,
    )

    # Configuração da tarefa gerada
    task_subtype_external_id = Column(
        Integer,
        ForeignKey("legal_one_task_subtypes.external_id"),
        nullable=False,
        index=True,
    )
    responsible_user_external_id = Column(
        Integer,
        ForeignKey("legal_one_users.external_id"),
        nullable=False,
        index=True,
    )

    priority = Column(String, nullable=False, default="Normal")  # Low, Normal, High
    due_business_days = Column(Integer, nullable=False, default=3)

    # Templates de texto (podem usar placeholders como {cnj}, {publication_date})
    description_template = Column(Text, nullable=True)
    notes_template = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    office = relationship(
        "LegalOneOffice",
        primaryjoin="TaskTemplate.office_external_id == LegalOneOffice.external_id",
        foreign_keys=[office_external_id],
    )
    task_subtype = relationship(
        "LegalOneTaskSubType",
        primaryjoin="TaskTemplate.task_subtype_external_id == LegalOneTaskSubType.external_id",
        foreign_keys=[task_subtype_external_id],
    )
    responsible_user = relationship(
        "LegalOneUser",
        primaryjoin="TaskTemplate.responsible_user_external_id == LegalOneUser.external_id",
        foreign_keys=[responsible_user_external_id],
    )
