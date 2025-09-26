# Agora, este é o novo conteúdo para: app/models/legal_one.py

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.session import Base
from .associations import squad_task_type_association


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

    # Este campo armazena o ID do grupo pai, que é mapeado na tabela TaskParentGroup.
    # A chave estrangeira e a relação foram removidas para refletir a nova arquitetura.
    parent_id = Column(Integer, index=True)

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