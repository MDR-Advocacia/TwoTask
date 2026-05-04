# app/api/v1/schemas.py

from pydantic import BaseModel, ConfigDict, computed_field, Field, field_validator
from typing import List, Optional, Dict, Any, Generic, TypeVar
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

# --- Schemas para Office (rep simples; full e' em outro endpoint) ---

class OfficeRef(BaseModel):
    """Referencia de escritorio responsavel exibida nas squads."""
    external_id: int
    name: str
    path: Optional[str] = None
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
        A propriedade 'squad_members' é carregada via joinedload na query da API.
        """
        if not hasattr(self, 'squad_members') or not self.squad_members:
            return []

        squad_dict = {member.squad.id: member.squad for member in self.squad_members if member.squad}
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
    is_assistant: bool = False
    user: LegalOneUser
    model_config = ConfigDict(from_attributes=True)

class Squad(BaseModel):
    """
    Schema de resposta para um Squad, incluindo escritorio responsavel e membros.
    """
    id: int
    name: str
    is_active: bool
    office_external_id: Optional[int] = None
    office: Optional[OfficeRef] = None
    members: List[SquadMember] = []
    model_config = ConfigDict(from_attributes=True)


# --- Schemas para Gerenciamento de Squads (Admin) ---

class SquadMemberSchema(BaseModel):
    """Schema para definir um membro ao criar/atualizar um squad."""
    user_id: int
    is_leader: bool = False
    is_assistant: bool = False


class SquadMemberRoleUpdate(BaseModel):
    """Schema pra PATCH em squad_members (toggle leader/assistant).

    Validacao no servico: max 1 leader e 1 assistant por squad. Quando
    o frontend marca outro membro, o servico desmarca o anterior antes.
    """
    is_leader: Optional[bool] = None
    is_assistant: Optional[bool] = None


class SquadMemberAddRequest(BaseModel):
    """Schema pra adicionar um user a uma squad."""
    user_id: int
    is_leader: bool = False
    is_assistant: bool = False


class AssistantResolution(BaseModel):
    """Resposta do GET /squads/assistant-of/{user_external_id}."""
    user_external_id: int
    squad_id: Optional[int] = None
    squad_name: Optional[str] = None
    fallback_reason: Optional[str] = None

class SquadCreateSchema(BaseModel):
    name: str
    office_external_id: int
    members: List[SquadMemberSchema] = []

class SquadUpdateSchema(BaseModel):
    name: Optional[str] = None
    office_external_id: Optional[int] = None
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
    data_agendamento: Optional[str] = None
    setor: Optional[str] = None
    id: Optional[int] = None
    numero_solicitacao: Optional[str] = None
    titulo: Optional[str] = None
    npj_direcionador: Optional[str] = None
    prazo: Optional[str] = None  # <--- CORREÇÃO PRINCIPAL
    texto_dmi: Optional[str] = None
    polo: Optional[str] = None
    recebido_em: Optional[str] = None
    anotacao: Optional[str] = None
    status: Optional[str] = None
    status_sistema: Optional[str] = None

    @field_validator("numero_processo")
    @classmethod
    def format_process_number_to_cnj(cls, v: str) -> str:
        """
        Garante que o número do processo esteja sempre no formato CNJ.
        """
        if v: # Adiciona verificação para não falhar em None
            return format_cnj(v)
        return v
    
    model_config = ConfigDict(extra="allow")


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
    fingerprint: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class BatchExecutionResponse(BaseModel):
    id: int
    source: str
    source_filename: Optional[str] = None
    requested_by_email: Optional[str] = None
    status: str
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

# Schemas para o endpoint de dados de criação de tarefa
class SubTypeSchema(BaseModel):
    id: int
    name: str

class HierarchicalTaskTypeSchema(BaseModel):
    id: int
    name: str
    sub_types: List[SubTypeSchema] = []

class UserSchema(BaseModel):
    id: int
    name: str
    external_id: int

class TaskStatusSchema(BaseModel):
    id: int
    name: str

class TaskCreationDataResponse(BaseModel):
    task_types: List[HierarchicalTaskTypeSchema]
    users: List[UserSchema]
    task_statuses: List[TaskStatusSchema]

# Schemas para o endpoint de criação interativa
class InteractiveTaskPayload(BaseModel):
    cnj_number: str
    task_type_id: int
    sub_type_id: int
    responsible_external_id: int
    description: str
    due_date: str
    due_time: Optional[str] = None

class BatchInteractiveCreationRequest(BaseModel):
    tasks: List[InteractiveTaskPayload]
    source_filename: str

class TaskForRuleValidation(BaseModel):
    """
    Representa uma única tarefa simplificada, contendo apenas
    a informação necessária para a validação de regras.
    """
    selected_subtype_id: str = Field(..., alias='selectedSubTypeId') # Recebe o camelCase do frontend

class ValidatePublicationTasksRequest(BaseModel):
    """
    O payload que o frontend enviará, contendo a lista de
    tarefas de uma única publicação para serem validadas.
    """
    tasks: List[TaskForRuleValidation]

T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """
    Schema genérico para uma resposta paginada.
    """
    total_items: int
    total_pages: int
    page: int
    items_per_page: int
    items: List[T]

    model_config = ConfigDict(from_attributes=True)
