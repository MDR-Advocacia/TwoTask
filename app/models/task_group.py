# app/models/task_group.py

from sqlalchemy import Column, Integer, String
from app.db.session import Base

class TaskParentGroup(Base):
    """
    Tabela para armazenar os nomes personalizados dos grupos de tarefas pai.
    O 'id' desta tabela corresponde ao 'parent_id' da tabela 'legal_one_task_types'.
    """
    __tablename__ = 'task_parent_groups'

    id = Column(Integer, primary_key=True, index=True, comment="Corresponde ao parent_id de legal_one_task_types")
    name = Column(String, nullable=False, unique=True)