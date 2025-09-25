# app/api/v1/schemas.py

from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict, Any

# --- Schemas para a API Externa (Legal One) ---

class Relationship(BaseModel):
    id: int
    type: str

class ResponsibleUser(BaseModel):
    id: int
    name: str

class LegalOneTaskPayload(BaseModel):
    description: str
    case_id: int
    task_type_id: int
    deadline: str  # Formato: "YYYY-MM-DD"
    relationships: List[Relationship]
    responsibles: List[ResponsibleUser]

# --- Schema para o Gatilho de Tarefas (Interno) ---

class TaskTriggerPayload(BaseModel):
    task_type_id: int
    squad_ids: Optional[List[int]] = None
    squad_member_ids: Optional[List[int]] = None
    task_details: Dict[str, Any]

# --- Schema para a Criação de Tarefas a partir da UI ---
# Mantido para compatibilidade com o endpoint existente em tasks.py

class TaskCreationRequest(BaseModel):
    template_id: int
    squad_ids: List[int]
    process_numbers: List[str]
    due_date: str
    priority: str
    custom_fields: Dict[str, str]

# --- Schemas para Setores ---

class SectorBase(BaseModel):
    name: str

class SectorCreateSchema(SectorBase):
    pass

class SectorUpdateSchema(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class Sector(SectorBase):
    id: int
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


# --- Schemas para Usuários e Squads ---

class LegalOneUser(BaseModel):
    """
    Representa um usuário do Legal One, conforme retornado pela nossa API.
    """
    id: int
    name: str
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class SquadMember(BaseModel):
    """
    Representa a associação de um usuário a um squad, aninhando os detalhes do usuário.
    """
    id: int
    is_leader: bool
    user: LegalOneUser
    model_config = ConfigDict(from_attributes=True)

class Squad(BaseModel):
    """
    Schema de resposta para um Squad, incluindo o setor e os membros.
    """
    id: int
    name: str
    is_active: bool
    sector: Sector  # Aninha os detalhes do setor
    members: List[SquadMember] = []
    model_config = ConfigDict(from_attributes=True)


# --- Schemas para Gerenciamento de Squads (Admin) ---

class SquadMemberSchema(BaseModel):
    """Schema para definir um membro ao criar/atualizar um squad."""
    user_id: int
    is_leader: bool = False

class SquadCreateSchema(BaseModel):
    name: str
    sector_id: int
    members: List[SquadMemberSchema]

class SquadUpdateSchema(BaseModel):
    name: Optional[str] = None
    sector_id: Optional[int] = None
    members: Optional[List[SquadMemberSchema]] = None

# --- Schema para Task Templates ---

class TaskTemplate(BaseModel):
    id: int
    name: str
    description: Optional[str]
    estimated_time: Optional[str]
    fields: List[str]
    model_config = ConfigDict(from_attributes=True)