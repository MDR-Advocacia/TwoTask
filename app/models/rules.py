# app/models/rules.py

import enum
import uuid
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.legal_one import LegalOneUser, LegalOneTaskType, LegalOneOffice  # noqa: F401

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

# --- MODELO DE SQUAD ---
# Squad e' agrupada por escritorio responsavel (LegalOneOffice). O
# conceito de Sector foi removido em sqd002 (2026-05-04) — duplicava a
# arvore de offices que ja' e' o balizador em todo o resto do dominio
# (templates, intakes, publications).

class Squad(Base):
    """Equipe vinculada a um escritorio responsavel (LegalOneOffice)."""
    __tablename__ = 'squads'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # FK pro escritorio responsavel pela squad. Nullable=False na
    # logica do admin (validado no SquadService); coluna no SQL ficou
    # nullable=True na migration sqd002 pra suportar dados legados.
    office_external_id = Column(
        Integer,
        ForeignKey('legal_one_offices.external_id'),
        nullable=True,
        index=True,
    )
    office = relationship('LegalOneOffice', foreign_keys=[office_external_id])

    members = relationship('SquadMember', back_populates='squad', cascade="all, delete-orphan")

class SquadMember(Base):
    """ Tabela de associação que conecta um LegalOneUser a um Squad. """
    __tablename__ = 'squad_members'
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Chaves estrangeiras que formam a relação
    squad_id = Column(Integer, ForeignKey('squads.id'), nullable=False)
    legal_one_user_id = Column(Integer, ForeignKey('legal_one_users.id'), nullable=False)
    
    is_leader = Column(Boolean, default=False)
    # Recebe tarefas marcadas como `target_role='assistente'` no template.
    # Constraint logico (validado no admin, nao em SQL): max 1 assistente
    # por squad. Ver app/services/squad_assistant_resolver.py.
    is_assistant = Column(Boolean, default=False, nullable=False, server_default='false')

    # Relações para facilitar as consultas
    squad = relationship('Squad', back_populates='members')
    user = relationship('LegalOneUser')