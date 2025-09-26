# app/services/task_creation_service.py

import logging
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneApiClient

# --- Exceções Customizadas para clareza no tratamento de erros ---

class LawsuitNotFoundError(Exception):
    """Lançada quando um processo não é encontrado pelo CNJ."""
    def __init__(self, cnj: str):
        self.cnj = cnj
        super().__init__(f"Nenhum processo (lawsuit) encontrado para o CNJ: {cnj}")

class TaskCreationError(Exception):
    """Lançada quando a criação da tarefa principal falha no Legal One."""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"Falha ao criar a tarefa no Legal One: {detail}")

class TaskLinkingError(Exception):
    """Lançada quando o vínculo da tarefa ao processo falha."""
    pass

# --- Modelos de Dados (DTOs) para a Lógica do Serviço ---

class TaskParticipant(BaseModel):
    contact_id: int = Field(..., description="ID do contato (usuário) no Legal One.")
    is_responsible: bool = False
    is_requester: bool = False
    is_executer: bool = True # Padrão para executor

class TaskCreationRequest(BaseModel):
    cnj_number: str = Field(..., description="Número do processo (CNJ) ao qual a tarefa será vinculada.")
    task_payload: Dict[str, Any] = Field(..., description="Payload JSON para a criação da tarefa, conforme a API do Legal One.")
    participants: List[TaskParticipant] = Field([], description="Lista de participantes a serem adicionados à tarefa.")


class TaskCreationService:
    """
    Orquestra a criação de uma tarefa no Legal One, incluindo a busca pelo
    processo, a criação da tarefa, o vínculo e a adição de participantes.
    """
    def __init__(self, db: Session):
        self.db = db
        self.legal_one_client = LegalOneApiClient()
        self.logger = logging.getLogger(__name__)

    def create_full_task_process(self, request: TaskCreationRequest) -> Dict[str, Any]:
        """
        Executa o fluxo completo de criação de tarefa.
        1. Busca o processo pelo CNJ.
        2. Cria a tarefa.
        3. Vincula a tarefa ao processo.
        4. Adiciona os participantes.
        """
        # Passo 1: Buscar o processo
        self.logger.info(f"Iniciando processo de criação de tarefa para o CNJ: {request.cnj_number}")
        lawsuit = self.legal_one_client.search_lawsuit_by_cnj(request.cnj_number)
        if not lawsuit or 'id' not in lawsuit:
            raise LawsuitNotFoundError(request.cnj_number)
        
        lawsuit_id = lawsuit['id']
        self.logger.info(f"Processo ID {lawsuit_id} encontrado.")

        # Passo 2: Criar a tarefa
        created_task = self.legal_one_client.create_task(request.task_payload)
        if not created_task or 'id' not in created_task:
            raise TaskCreationError("A resposta da API não continha um ID de tarefa válido.")
            
        task_id = created_task['id']
        self.logger.info(f"Tarefa ID {task_id} criada com sucesso.")

        # Passo 3: Vincular a tarefa ao processo
        link_success = self.legal_one_client.link_task_to_lawsuit(task_id, lawsuit_id)
        if not link_success:
            # Em um cenário real, poderíamos tentar reverter a criação da tarefa
            self.logger.error(f"Falha crítica ao vincular a tarefa {task_id} ao processo {lawsuit_id}. A tarefa foi criada mas não está vinculada.")
            raise TaskLinkingError(f"Não foi possível vincular a tarefa {task_id} ao processo {lawsuit_id}.")
        
        self.logger.info("Vínculo com o processo realizado com sucesso.")

        # Passo 4: Adicionar participantes
        for participant in request.participants:
            self.legal_one_client.add_participant_to_task(
                task_id=task_id,
                contact_id=participant.contact_id,
                is_responsible=participant.is_responsible,
                is_requester=participant.is_requester,
                is_executer=participant.is_executer
            )
            # O tratamento de falha aqui é opcional. Pode-se optar por logar e continuar.
        
        self.logger.info(f"Processo de criação de tarefa para o CNJ {request.cnj_number} concluído.")
        
        return {
            "message": "Tarefa criada e vinculada com sucesso!",
            "created_task": created_task
        }