# file: app/core/dependencies.py

from app.services.legal_one_client import LegalOneApiClient
from app.services.task_creation_service import TaskCreationService
from app.services.orchestration_service import OrchestrationService

# --- Instâncias Singleton (criadas uma única vez e reutilizadas) ---

# Criamos uma única instância do cliente de API para toda a aplicação.
# Isso permite que ele gerencie o token de forma centralizada.
api_client = LegalOneApiClient()

# O Motor 1 depende do cliente de API.
task_creation_service = TaskCreationService(api_client=api_client)

# O Motor 2 depende de ambos.
orchestration_service = OrchestrationService(
    api_client=api_client, 
    task_service=task_creation_service
)

# --- Funções "Getter" para o FastAPI ---

def get_orchestration_service() -> OrchestrationService:
    """
    Esta função será usada pelo `Depends` do FastAPI para injetar
    a instância do serviço orquestrador no nosso endpoint.
    """
    return orchestration_service