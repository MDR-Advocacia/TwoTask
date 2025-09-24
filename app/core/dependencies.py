# --- CONTEÚDO COMPLETO E CORRIGIDO para: app/core/dependencies.py ---

from app.db.session import SessionLocal
from app.services.legal_one_client import LegalOneApiClient
from app.services.task_creation_service import TaskCreationService
from app.services.orchestration_service import OrchestrationService

# --- Instâncias Singleton (criadas uma única vez e reutilizadas) ---

api_client = LegalOneApiClient()
task_creation_service = TaskCreationService(api_client=api_client)
orchestration_service = OrchestrationService(
    api_client=api_client, 
    task_service=task_creation_service
)

# --- Funções "Getter" para o FastAPI ---

def get_orchestration_service() -> OrchestrationService:
    """
    Injeta a instância do serviço orquestrador no endpoint.
    """
    return orchestration_service

def get_db():
    """
    Dependência do FastAPI para obter uma sessão do banco de dados.
    Garante que a sessão seja sempre fechada após a requisição.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()