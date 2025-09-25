# app/models/rules.py

import enum
import uuid
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.db.session import Base
# Importar modelos relacionados de um único local para clareza
from app.models.legal_one import LegalOneUser, LegalOneTaskType

class ActionLogic(enum.Enum):
    """
    Define as lógicas de distribuição (Ações) que o administrador
    poderá escolher. O sistema virá com estas lógicas pré-programadas.
    """
    ASSIGN_TO_LAWSUIT_LEADER = "ASSIGN_TO_LAWSUIT_LEADER"
    ASSIGN_TO_LEADER_ASSISTANT = "ASSIGN_TO_LEADER_ASSISTANT"

class Rule(Base):
    """
    A Regra de negócio principal.
    Ex: 'Contestações BB para o time do Responsável Principal'.
    """
    __tablename__ = 'rules'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)
    is_active = Column(Boolean, default=True, nullable=False)

    conditions = relationship('RuleCondition', back_populates='rule', cascade="all, delete-orphan")
    task_types = relationship('RuleTaskTypeAssociation', back_populates='rule', cascade="all, delete-orphan")
    action = relationship('RuleAction', uselist=False, back_populates='rule', cascade="all, delete-orphan")

class RuleTaskTypeAssociation(Base):
    """ Tabela de associação para vincular uma Regra a múltiplos Tipos de Tarefa. """
    __tablename__ = 'rule_task_type_associations'

    rule_id = Column(Integer, ForeignKey('rules.id'), primary_key=True)
    task_type_id = Column(Integer, ForeignKey('legal_one_task_types.id'), primary_key=True)

    rule = relationship('Rule', back_populates='task_types')
    task_type = relationship('LegalOneTaskType')

class RuleCondition(Base):
    """
    Define uma condição específica (o 'SE') para uma Regra.
    Uma regra pode ter várias condições. Ex:
    SE 'responsible_office_id' É IGUAL A '123' E ...
    """
    __tablename__ = 'rule_conditions'

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey('rules.id'), nullable=False)
    field_name = Column(String, nullable=False)
    operator = Column(String, nullable=False, default='EQUALS')
    value = Column(String, nullable=False)

    rule = relationship('Rule', back_populates='conditions')

class RuleAction(Base):
    """
    Define a Ação (o 'ENTÃO') a ser executada se todas as
    condições de uma Regra forem satisfeitas.
    """
    __tablename__ = 'rule_actions'

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey('rules.id'), unique=True, nullable=False)
    logic = Column(Enum(ActionLogic), nullable=False)

    rule = relationship('Rule', back_populates='action')

class Squad(Base):
    """
    Representa uma equipe ou squad, contendo vários membros.
    """
    __tablename__ = 'squads'
    
    id = Column(Integer, primary_key=True, index=True)
    # Usar String para UUID garante compatibilidade com SQLite
    external_id = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    
    # --- A CORREÇÃO ESTÁ AQUI ---
    # A restrição `unique=True` foi removida para permitir que múltiplos squads
    # pertençam ao mesmo setor.
    sector = Column(String, index=True)
    
    is_active = Column(Boolean, default=True, nullable=False)
    
    members = relationship('SquadMember', back_populates='squad', cascade="all, delete-orphan")

class SquadMember(Base):
    """
    Representa um membro de uma squad. Pode ou não estar associado a um
    usuário do Legal One.
    """
    __tablename__ = 'squad_members'
    
    id = Column(Integer, primary_key=True, index=True)
    # Usar String para UUID garante compatibilidade com SQLite
    external_id = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    role = Column(String)
    is_leader = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    squad_id = Column(Integer, ForeignKey('squads.id'), nullable=False)
    legal_one_user_id = Column(Integer, ForeignKey('legal_one_users.id'), nullable=True)
    
    squad = relationship('Squad', back_populates='members')
    legal_one_user = relationship('LegalOneUser')