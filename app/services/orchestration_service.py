# file: app/services/orchestration_service.py

import logging
from datetime import datetime, timedelta

# Importa os componentes que o Orquestrador irá usar
from app.services.legal_one_client import LegalOneApiClient
from app.services.task_creation_service import TaskCreationService
from app.api.v1.schemas import TaskTriggerPayload
from app.models.canonical import CreateTaskRequest, CanonicalTask, RelatedEntity

# Custom exceptions para um tratamento de erro mais claro
class ProcessNotFoundError(Exception):
    pass

class MissingResponsibleUserError(Exception):
    pass

class OrchestrationService:
    """
    Motor 2: O cérebro da aplicação. Orquestra o fluxo de enriquecimento
    e criação de tarefas.
    """

    def __init__(self, api_client: LegalOneApiClient, task_service: TaskCreationService):
        """
        Inicializa o serviço com suas dependências (outros serviços).
        """
        self.api_client = api_client
        self.task_service = task_service

    def _apply_business_rules(self, trigger: TaskTriggerPayload, lawsuit_data: dict) -> CanonicalTask:
        """
        Aplica as regras de negócio para transformar os dados brutos e enriquecidos
        em uma tarefa canônica pronta para ser criada.

        **Este é o local para customizar a lógica de negócio.**
        """
        logging.info(f"Aplicando regras de negócio para o processo {trigger.process_number}")

        # Regra 1: Definir o responsável.
        # Lógica: Usar o primeiro usuário responsável encontrado no processo.
        responsible_users = lawsuit_data.get("responsibleUsers", [])
        if not responsible_users or not responsible_users[0].get("id"):
            raise MissingResponsibleUserError(f"O processo {trigger.process_number} não possui um usuário responsável com ID.")
        
        owner_id = responsible_users[0]["id"]

        # Regra 2: Definir o título e a descrição da tarefa.
        title = f"Analisar Publicação no Processo {trigger.process_number}"
        description = f"Tarefa gerada automaticamente pelo sistema de integração a partir do evento ID: {trigger.event_source_id}."

        # Regra 3: Definir o prazo.
        # Lógica: Prazo de 5 dias úteis a partir de hoje. (Lógica simplificada)
        due_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

        # Regra 4: Definir os vínculos.
        # Lógica: Vincular ao processo e ao cliente principal do processo.
        process_id = lawsuit_data["id"]
        main_contact_id = lawsuit_data.get("mainContactId")
        
        related_to = [RelatedEntity(type="Processo", legal_one_id=process_id)]
        if main_contact_id:
            # Assumindo que mainContactId se refere a uma Empresa/Cliente
            related_to.append(RelatedEntity(type="Empresa", legal_one_id=main_contact_id))

        # Monta o objeto CanonicalTask com base nas regras aplicadas.
        return CanonicalTask(
            title=title,
            description=description,
            dueDate=due_date,
            owner_id=owner_id,
            priority="High", # Exemplo de prioridade fixa
            relatedTo=related_to
        )


    def handle_task_trigger(self, trigger: TaskTriggerPayload) -> dict:
        """
        Ponto de entrada principal do orquestrador.
        Executa o fluxo completo: enriquecimento, regras de negócio e chamada ao serviço de criação.
        """
        logging.info(f"Iniciando orquestração para o gatilho ID: {trigger.event_source_id}")

        # 1. ENRIQUECIMENTO: Buscar dados do processo na API do Legal One.
        lawsuit_data = self.api_client.get_lawsuit_by_folder(
            folder_number=trigger.process_number,
            tenant_id=trigger.tenant_id
        )
        if not lawsuit_data:
            raise ProcessNotFoundError(f"Processo com número '{trigger.process_number}' não encontrado no Legal One para o tenant '{trigger.tenant_id}'.")

        # 2. LÓGICA DE NEGÓCIO: Aplicar as regras para definir os detalhes da tarefa.
        canonical_task = self._apply_business_rules(trigger, lawsuit_data)

        # 3. MONTAGEM: Montar o payload final para o Motor 1 (TaskCreationService).
        final_request = CreateTaskRequest(
            tenantId=trigger.tenant_id,
            idempotencyKey=trigger.event_source_id, # Reutiliza o ID do evento de origem como chave de idempotência
            sourceSystem={"name": trigger.source_system_name},
            task=canonical_task
        )

        # 4. EXECUÇÃO: Chamar o Motor 1 para criar a tarefa.
        logging.info(f"Encaminhando para o serviço de criação de tarefas. Chave de idempotência: {final_request.idempotency_key}")
        result = self.task_service.create_task(final_request)

        return result