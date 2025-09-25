# app/models/rules.py

import enum
import uuid
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.legal_one import LegalOneUser, LegalOneTaskType

class ActionLogic(enum.Enum):
    ASSIGN_TO_LAWSUIT_LEADER = "ASSIGN_TO_LAWSUIT_LEADER"
    ASSIGN_TO_LEADER_ASSISTANT = "ASSIGN_TO_LEADER_ASSISTANT"

class Rule(Base):
    __tablename__ = 'rules'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)
    is_active = Column(Boolean, default=True, nullable=False)
    conditions = relationship('RuleCondition', back_populates='rule', cascade="all, delete-orphan")
    task_types = relationship('RuleTaskTypeAssociation', back_populates='rule', cascade="all, delete-orphan")
    action = relationship('RuleAction', uselist=False, back_populates='rule', cascade="all, delete-orphan")

class RuleTaskTypeAssociation(Base):
    __tablename__ = 'rule_task_type_associations'
    rule_id = Column(Integer, ForeignKey('rules.id'), primary_key=True)
    task_type_id = Column(Integer, ForeignKey('legal_one_task_types.id'), primary_key=True)
    rule = relationship('Rule', back_populates='task_types')
    task_type = relationship('LegalOneTaskType')

class RuleCondition(Base):
    __tablename__ = 'rule_conditions'
    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey('rules.id'), nullable=False)
    field_name = Column(String, nullable=False)
    operator = Column(String, nullable=False, default='EQUALS')
    value = Column(String, nullable=False)
    rule = relationship('Rule', back_populates='conditions')

class RuleAction(Base):
    __tablename__ = 'rule_actions'
    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey('rules.id'), unique=True, nullable=False)
    logic = Column(Enum(ActionLogic), nullable=False)
    rule = relationship('Rule', back_populates='action')

# --- MODELOS DE SQUAD SIMPLIFICADOS ---

class Squad(Base):
    """ Representa uma equipe ou squad criada e gerenciada internamente. """
    __tablename__ = 'squads'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True) # Nome do squad deve ser único
    sector = Column(String, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # A relação agora é com a nova tabela de associação `squad_members`
    members = relationship('SquadMember', back_populates='squad', cascade="all, delete-orphan")

class SquadMember(Base):
    """ Tabela de associação que conecta um LegalOneUser a um Squad. """
    __tablename__ = 'squad_members'
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Chaves estrangeiras que formam a relação
    squad_id = Column(Integer, ForeignKey('squads.id'), nullable=False)
    legal_one_user_id = Column(Integer, ForeignKey('legal_one_users.id'), nullable=False)
    
    is_leader = Column(Boolean, default=False)
    
    # Relações para facilitar as consultas
    squad = relationship('Squad', back_populates='members')
    user = relationship('LegalOneUser')