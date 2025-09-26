# app/models/task_group.py

from sqlalchemy import Column, Integer, String
from app.db.session import Base

class TaskParentGroup(Base):
    """
    Representa um grupo pai para tipos de tarefa.
    Esta tabela armazena o mapeamento manual entre um ID de grupo (parent_id)
    e o nome exibido para esse grupo, que pode ser editado pelo administrador.
    """
    __tablename__ = 'task_parent_groups'

    id = Column(Integer, primary_key=True, index=True, comment="Corresponde ao 'parent_id' usado nos tipos de tarefa do Legal One")
    name = Column(String, nullable=False, comment="O nome do grupo de tarefas, ex: 'Audiência', 'Prazo'")