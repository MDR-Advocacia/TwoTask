# CONTEÚDO COMPLETO E CORRIGIDO para: app/api/v1/schemas.py

from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict, Any

# --- Schemas para os Usuários do Legal One ---
class LegalOneUserBase(BaseModel):
    id: int
    name: str

class LegalOneUser(LegalOneUserBase):
    model_config = ConfigDict(from_attributes=True)

# --- Schemas para os Membros de Squad ---
class SquadMemberBase(BaseModel):
    id: int
    name: str
    email: str
    role: Optional[str] = None
    is_active: bool
    is_leader: bool
    legal_one_user_id: Optional[int] = None

class SquadMember(SquadMemberBase):
    model_config = ConfigDict(from_attributes=True)

# --- Schemas para os Squads ---
class SquadBase(BaseModel):
    id: int
    name: str
    sector: str

class Squad(SquadBase):
    members: List[SquadMember] = []
    model_config = ConfigDict(from_attributes=True)

# --- Schema para a atualização de vínculo ---
class SquadMemberLinkUpdate(BaseModel):
    squad_member_id: int
    legal_one_user_id: Optional[int] = None

# --- Schema para o Gatilho de Tarefas (A CORREÇÃO) ---
# Este era o schema que estava faltando
class TaskTriggerPayload(BaseModel):
    task_type_id: int
    squad_ids: Optional[List[int]] = None
    squad_member_ids: Optional[List[int]] = None
    task_details: Dict[str, Any]