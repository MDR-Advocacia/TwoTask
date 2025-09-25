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

# --- Schemas para Usuários e Squads ---

class LegalOneUser(BaseModel):
    id: int
    name: str
    role: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class SquadMember(BaseModel):
    id: int
    name: str
    role: Optional[str] = None
    is_active: bool
    is_leader: bool
    legal_one_user_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class Squad(BaseModel):
    id: int
    name: str
    sector: Optional[str] = None
    members: List[SquadMember] = []
    model_config = ConfigDict(from_attributes=True)
# --- Schemas para Gerenciamento de Squads (Admin) ---

class SquadCreateSchema(BaseModel):
    name: str
    member_ids: List[int]

class SquadUpdateSchema(BaseModel):
    name: Optional[str] = None
    member_ids: Optional[List[int]] = None

class SquadMemberLinkUpdate(BaseModel):
    squad_member_id: int
    legal_one_user_id: Optional[int] = None

# --- Schema para Task Templates ---

class TaskTemplate(BaseModel):
    id: int
    name: str
    description: Optional[str]
    estimated_time: Optional[str]
    fields: List[str]
    model_config = ConfigDict(from_attributes=True)