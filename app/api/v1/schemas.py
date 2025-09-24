# --- CONTEÚDO COMPLETO E CORRIGIDO para: app/api/v1/schemas.py ---

from pydantic import BaseModel, Field
from typing import Optional

class TaskTriggerPayload(BaseModel):
    """
    Payload de entrada para o Orquestrador. Contém apenas o mínimo 
    necessário para iniciar o processo.
    """
    tenant_id: str = Field(..., alias="tenantId")
    event_source_id: str = Field(..., alias="eventSourceId", description="ID único do evento de origem, para idempotência.")
    source_system_name: str = Field(..., alias="sourceSystemName", description="Nome do sistema que disparou o gatilho. Ex: 'SistemaDePublicacoes'")
    process_number: str = Field(..., alias="processNumber", description="O número do processo (pasta) a ser enriquecido.")

class SquadMemberLinkUpdate(BaseModel):
    """
    Payload para a requisição de atualização do vínculo entre
    um membro de squad e um usuário do Legal One.
    """
    squad_member_id: int
    legal_one_user_id: Optional[int] = None