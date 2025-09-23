# Agora, este é o novo conteúdo para: app/models/legal_one.py

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.session import Base

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

    # Auto-relacionamento para a estrutura de árvore
    parent_id = Column(Integer, ForeignKey('legal_one_task_types.id'))
    parent = relationship('LegalOneTaskType', remote_side=[id], back_populates='sub_types')
    sub_types = relationship('LegalOneTaskType', back_populates='parent')

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
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)