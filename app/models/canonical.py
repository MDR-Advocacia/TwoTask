# file: app/models/canonical.py

from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from ..db.session import Base

class RelatedEntity(BaseModel):
    """Representa uma entidade a ser vinculada à tarefa em nosso modelo."""
    entity_type: Literal["Processo", "Empresa", "Contato"] = Field(..., alias="type")
    legal_one_id: int

class CanonicalTask(BaseModel):
    """Modelo de dados padronizado (canônico) para uma tarefa dentro do nosso sistema."""
    title: str
    description: Optional[str] = None
    due_date: str = Field(..., alias="dueDate") # Espera o formato "YYYY-MM-DD"
    owner_id: int # ID numérico do usuário responsável no Legal One
    priority: Literal["Normal", "High", "Low"]
    related_to: List[RelatedEntity] = Field([], alias="relatedTo")

class CreateTaskRequest(BaseModel):
    """
    Modelo para o payload completo que o nosso Serviço Principal (Motor 1) 
    espera receber.
    """
    tenant_id: str = Field(..., alias="tenantId")
    idempotency_key: str = Field(..., alias="idempotencyKey")
    source_system: dict = Field(..., alias="sourceSystem")
    task: CanonicalTask