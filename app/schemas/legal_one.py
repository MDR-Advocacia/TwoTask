# Criar o arquivo: app/schemas/legal_one.py
# (Mover o conteúdo do seu app/models/legal_one.py original para cá)

from typing import List, Optional
from pydantic import BaseModel, Field

class ResponsibleUser(BaseModel):
    """Estrutura para o responsável pela tarefa no Legal One."""
    id: int

class Relationship(BaseModel):
    """Estrutura para um vínculo (relacionamento) no Legal One."""
    link_id: int = Field(..., alias="linkId")
    link_type: str = Field(..., alias="linkType") # Ex: "Litigation"

class LegalOneTaskPayload(BaseModel):
    """
    Modelo do Payload exato a ser enviado no corpo da requisição
    POST /tasks para a API do Legal One.
    """
    subject: str
    description: Optional[str] = None
    due_date: str = Field(..., alias="dueDate") # Espera o formato "YYYY-MM-DDTHH:mm:ss"
    is_private: bool = Field(False, alias="isPrivate")
    responsible_users: List[ResponsibleUser] = Field(..., alias="responsibleUsers")
    relationships: List[Relationship]