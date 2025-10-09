# app/models/legal_one.py

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.session import Base
from .associations import squad_task_type_association

class LegalOneTaskSubType(Base):
    """
    REPRESENTAÇÃO NO BANCO DE DADOS de um subtipo de tarefa sincronizado do L1.
    Está sempre associado a um LegalOneTaskType pai.
    """
    __tablename__ = 'legal_one_task_subtypes'

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False,
                         comment="ID original da entidade no Legal One")
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    # Chave estrangeira que aponta para o ID externo do tipo pai.
    # Isso reflete a estrutura da API do Legal One.
    parent_type_external_id = Column(Integer, ForeignKey('legal_one_task_types.external_id'), index=True, nullable=False)

    # Relação para acessar o objeto pai a partir do subtipo
    parent_type = relationship('LegalOneTaskType', back_populates='subtypes')


class LegalOneTaskType(Base):
    """
    REPRESENTAÇÃO NO BANCO DE DADOS de um tipo de tarefa sincronizado do L1.
    Armazena a estrutura hierárquica (Tipo -> Subtipo) das tarefas.
    """
    __tablename__ = 'legal_one_task_types'

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False,
                         comment="ID original da entidade no Legal One")
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    
    # Relação para acessar todos os subtipos associados a este tipo
    subtypes = relationship('LegalOneTaskSubType', back_populates='parent_type', cascade="all, delete-orphan")

    # Relação muitos-para-muitos com Squad (permanece a mesma)
    squads = relationship(
        'Squad',
        secondary=squad_task_type_association,
        back_populates='task_types'
    )

class LegalOneOffice(Base):
    """
    REPRESENTAÇÃO NO BANCO DE DADOS de um escritório sincronizado do L1.
    """
    __tablename__ = 'legal_one_offices'

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False,
                         comment="ID original da entidade no Legal One")
    name = Column(String, nullable=False)
    path = Column(String, comment="Caminho completo, ex: 'Jurídico / Filial SP / Contencioso'")
    is_active = Column(Boolean, default=True)

class LegalOneUser(Base):
    """
    Representa um usuário sincronizado do Legal One.
    Esta tabela serve como um cache local para validar e associar
    usuários ao atribuir tarefas.
    """
    __tablename__ = 'legal_one_users'

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False,
                         comment="ID original do usuário no Legal One")
    name = Column(String, index=True, nullable=False)
    email = Column(String, index=True, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relação para acessar as associações de squad
    squad_members = relationship('SquadMember', back_populates='user')
     
    # --- CAMPO ADICIONADO ---
    hashed_password = Column(String, nullable=True) # Permite nulo inicialmente
    
    is_active = Column(Boolean, default=True, nullable=False)

    # Relação para acessar as associações de squad
    squad_members = relationship('SquadMember', back_populates='user')