# Criar o arquivo: app/models/rules.py

import enum
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.db.session import Base

class ActionLogic(enum.Enum):
    """
    Define as lógicas de distribuição (Ações) que o administrador
    poderá escolher. O sistema virá com estas lógicas pré-programadas.
    """
    ASSIGN_TO_LAWSUIT_LEADER = "ASSIGN_TO_LAWSUIT_LEADER" # Atribuir ao Responsável Principal da pasta
    ASSIGN_TO_LEADER_ASSISTANT = "ASSIGN_TO_LEADER_ASSISTANT" # Atribuir a um Assistente do Responsável

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

    # Relacionamentos
    conditions = relationship('RuleCondition', back_populates='rule', cascade="all, delete-orphan")
    task_types = relationship('RuleTaskTypeAssociation', back_populates='rule', cascade="all, delete-orphan")
    action = relationship('RuleAction', uselist=False, back_populates='rule', cascade="all, delete-orphan")

class RuleTaskTypeAssociation(Base):
    """ Tabela de associação para vincular uma Regra a múltiplos Tipos de Tarefa. """
    __tablename__ = 'rule_task_type_associations'

    rule_id = Column(Integer, ForeignKey('rules.id'), primary_key=True)
    task_type_id = Column(Integer, ForeignKey('legal_one_task_types.id'), primary_key=True)

    rule = relationship('Rule', back_populates='task_types')
    # Adicione um relacionamento para a task_type se precisar navegar no sentido inverso
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

    # O campo do dado de entrada que será verificado.
    # Ex: 'responsible_office_id', 'client_id'
    field_name = Column(String, nullable=False)

    # O operador de comparação. Começaremos com 'EQUALS'.
    operator = Column(String, nullable=False, default='EQUALS')

    # O valor com o qual o campo será comparado. Ex: '123'
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

    # A lógica de distribuição a ser aplicada.
    logic = Column(Enum(ActionLogic), nullable=False)

    rule = relationship('Rule', back_populates='action')