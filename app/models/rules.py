# Mova este código para um novo arquivo: app/models/rules.py

import enum
from datetime import datetime

from sqlalchemy import (Column, Integer, String, DateTime, Boolean, Enum as SQLAlchemyEnum,
                        ForeignKey, Table, JSON)
from sqlalchemy.orm import relationship, declarative_base

# Base declarativa padrão para os modelos do SQLAlchemy
Base = declarative_base()

# --- Enums de Negócio ---

class DistributionActionEnum(str, enum.Enum):
    """Define as ações de distribuição possíveis para uma regra."""
    ASSIGN_TO_LEADER = "ASSIGN_TO_LEADER"
    ASSIGN_TO_ASSISTANT_ROUND_ROBIN = "ASSIGN_TO_ASSISTANT_ROUND_ROBIN"

# --- Tabelas de Metadados Sincronizados ---

class LegalOneTaskType(Base):
    """Representa um tipo de tarefa sincronizado do Legal One."""
    __tablename__ = 'legal_one_task_types'

    id = Column(Integer, primary_key=True, index=True)
    l1_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    parent_type = Column(String, nullable=True)
    subtype = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<LegalOneTaskType(name='{self.name}')>"

# Adicionar a tabela de escritórios quando formos implementar a sincronização
# class LegalOneOffice(Base): ...

# --- Tabelas do Motor de Regras ---

# Tabela de associação Muitos-para-Muitos entre Regras e Tipos de Tarefa
rule_task_type_association = Table(
    'rule_task_type_association',
    Base.metadata,
    Column('rule_id', Integer, ForeignKey('rules.id'), primary_key=True),
    Column('task_type_id', Integer, ForeignKey('legal_one_task_types.id'), primary_key=True)
)

class Rule(Base):
    """A regra principal de distribuição."""
    __tablename__ = 'rules'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    action = Column(SQLAlchemyEnum(DistributionActionEnum), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamento Muitos-para-Muitos com os tipos de tarefa
    task_types = relationship(
        "LegalOneTaskType",
        secondary=rule_task_type_association,
        backref="rules"
    )
    
    # Relacionamento Um-para-Muitos com as condições
    conditions = relationship("RuleCondition", back_populates="rule", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Rule(name='{self.name}', action='{self.action.value}')>"

class RuleCondition(Base):
    """Uma condição que deve ser satisfeita para uma regra ser aplicada."""
    __tablename__ = 'rule_conditions'

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey('rules.id'), nullable=False)
    
    # Ex: 'office.id', 'process_type.name'
    field_name = Column(String, nullable=False) 
    
    # Ex: 'EQUALS', 'IN', 'NOT_EQUALS'
    operator = Column(String, nullable=False) 
    
    # Usamos JSON para flexibilidade (pode ser string, número, lista de strings, etc.)
    value = Column(JSON, nullable=False)

    rule = relationship("Rule", back_populates="conditions")

    def __repr__(self):
        return f"<RuleCondition(field='{self.field_name}', op='{self.operator}')>"