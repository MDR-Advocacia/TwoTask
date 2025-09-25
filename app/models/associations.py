from sqlalchemy import Table, Column, Integer, ForeignKey
from app.db.session import Base

squad_task_type_association = Table(
    'squad_task_type_association', Base.metadata,
    Column('squad_id', Integer, ForeignKey('squads.id'), primary_key=True),
    Column('task_type_id', Integer, ForeignKey('legal_one_task_types.id'), primary_key=True)
)