# app/api/v1/schemas.py

from pydantic import BaseModel, ConfigDict, computed_field, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.core.utils import format_cnj

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

class UserSquadInfo(BaseModel):
    """Schema simples para representar o squad de um usuário."""
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class UserWithSquads(BaseModel):
    """
    Schema para um usuário do Legal One com a lista de squads associados.
    Usado para popular seletores no frontend.
    """
    id: int
    external_id: int
    name: str

    @computed_field
    def squads(self) -> List[UserSquadInfo]:
        """
        Calcula a lista de squads únicos aos quais o usuário pertence.
        A propriedade 'members' é carregada via joinedload na query da API.
        """
        if not hasattr(self, 'members') or not self.members:
            return []
        
        squad_dict = {member.squad.id: member.squad for member in self.members if member.squad}
        sorted_squads = sorted(squad_dict.values(), key=lambda s: s.name)
        
        return [UserSquadInfo.from_orm(s) for s in sorted_squads]

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class LegalOneUser(BaseModel):
    """
    Representa um usuário do Legal One, conforme retornado pela nossa API.
    """
    id: int
    external_id: int
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


class ProcessoResponsavel(BaseModel):
    numero_processo: str
    id_responsavel: int
    observacao: Optional[str] = None

    @field_validator("numero_processo")
    @classmethod
    def format_process_number_to_cnj(cls, v: str) -> str:
        """
        Garante que o número do processo esteja sempre no formato CNJ.
        """
        return format_cnj(v)


class BatchTaskCreationRequest(BaseModel):
    fonte: str
    processos: List[ProcessoResponsavel]
    file_content: Optional[bytes] = None # <-- ADICIONAR ESTA LINHA
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
# --- Schemas para o Dashboard de Lotes ---

class BatchExecutionItemResponse(BaseModel):
    id: int
    process_number: str
    status: str
    created_task_id: Optional[int] = None
    error_message: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class BatchExecutionResponse(BaseModel):
    id: int
    source: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_items: int
    success_count: int
    failure_count: int
    items: List[BatchExecutionItemResponse] = []
    
    model_config = ConfigDict(from_attributes=True)

# --- ADIÇÃO: Schemas para Autenticação ---

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None