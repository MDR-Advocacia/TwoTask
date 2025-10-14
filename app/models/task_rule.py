from sqlalchemy import Column, Integer, ForeignKey, String
from sqlalchemy.orm import relationship
from app.db.session import Base

class TaskCoRequisiteRule(Base):
    """
    Define uma regra de co-ocorrência: se uma tarefa do tipo 'primary' for
    criada para um processo, uma tarefa do tipo 'secondary' também deve ser.
    """
    __tablename__ = 'task_corequisite_rules'

    id = Column(Integer, primary_key=True, index=True)
    
    primary_subtype_id = Column(Integer, ForeignKey('legal_one_task_subtypes.id'), nullable=False)
    secondary_subtype_id = Column(Integer, ForeignKey('legal_one_task_subtypes.id'), nullable=False)
    description = Column(String, nullable=True, comment="Descrição da regra. Ex: 'Audiência sempre requer Preposto.'")

    primary_subtype = relationship("LegalOneTaskSubType", foreign_keys=[primary_subtype_id])
    secondary_subtype = relationship("LegalOneTaskSubType", foreign_keys=[secondary_subtype_id])