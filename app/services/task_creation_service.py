# file: app/services/task_creation_service.py

from datetime import datetime
from app.models.canonical import CreateTaskRequest
from app.models.legal_one import LegalOneTaskPayload, ResponsibleUser, Relationship
from app.services.legal_one_client import LegalOneApiClient

class TaskCreationService:
    """
    Motor 1: Serviço de alto nível que contém a lógica de negócio
    para a criação de tarefas.
    """

    def __init__(self, api_client: LegalOneApiClient):
        """
        Inicializa o serviço com suas dependências.

        Args:
            api_client: Uma instância do cliente de API para o Legal One.
        """
        self.api_client = api_client
        # A lógica de idempotência seria injetada aqui.
        # Ex: self.idempotency_repository = IdempotencyRepository()

    def _map_to_legal_one_payload(self, request: CreateTaskRequest) -> LegalOneTaskPayload:
        """
        Mapeia (traduz) nosso modelo de dados canônico para o formato de payload 
        esperado pela API do Legal One.
        """
        task = request.task

        # A API espera um datetime completo, então adicionamos a hora final do dia.
        due_date_obj = datetime.strptime(task.due_date, "%Y-%m-%d")
        formatted_due_date = due_date_obj.strftime("%Y-%m-%dT23:59:59")

        # Mapeia as entidades relacionadas para o formato de 'relationships'
        relationships = []
        link_type_map = {
            "Processo": "Litigation",
            "Empresa": "Company",
            "Contato": "Contact"
        }
        for entity in task.related_to:
            link_type = link_type_map.get(entity.entity_type)
            if link_type:
                relationships.append(Relationship(
                    linkId=entity.legal_one_id,
                    linkType=link_type
                ))

        return LegalOneTaskPayload(
            subject=task.title,
            description=task.description,
            dueDate=formatted_due_date,
            responsibleUsers=[ResponsibleUser(id=task.owner_id)],
            relationships=relationships
        )

    def create_task(self, request: CreateTaskRequest) -> dict:
        """
        Orquestra a criação de uma tarefa: valida idempotência, mapeia os dados
        e chama o cliente da API.
        """
        # Passo 1: Checagem de Idempotência (espaço reservado para a lógica real)
        # if self.idempotency_repository.exists(request.idempotency_key):
        #     raise ConflictError("A tarefa com esta chave de idempotência já foi criada.")

        # Passo 2: Mapear o payload canônico para o formato do Legal One
        legal_one_payload = self._map_to_legal_one_payload(request)

        # Passo 3: Chamar o cliente da API
        # O método .dict() do Pydantic converte nosso modelo em um dicionário.
        # by_alias=True garante que 'dueDate' seja usado em vez de 'due_date'.
        # exclude_none=True remove campos opcionais que não foram preenchidos (ex: description).
        created_task_response = self.api_client.post_task(
            task_payload=legal_one_payload.dict(by_alias=True, exclude_none=True),
            tenant_id=request.tenant_id
        )

        # Passo 4: Salvar o resultado para futuras checagens de idempotência
        # self.idempotency_repository.save(request.idempotency_key, created_task_response['id'])

        # Passo 5: Retornar uma resposta padronizada e rica
        return {
            "status": "success",
            "message": "Tarefa criada com sucesso no Legal One.",
            "legalOneTaskId": created_task_response.get("id"),
            "sourceSystem": request.source_system
        }