# app/core/dependencies.py

from sqlalchemy.orm import Session
from fastapi import Depends
from app.db.session import SessionLocal
from app.services.legal_one_client import LegalOneApiClient
from app.services.task_creation_service import TaskCreationService
from app.services.squad_sync_service import SquadSyncService
from app.services.orchestration_service import OrchestrationService # Importa o serviço

# Função de dependência para obter a sessão do banco de dados
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Função de dependência para obter o cliente da API
def get_api_client() -> LegalOneApiClient:
    return LegalOneApiClient()

# Função de dependência para o serviço de criação de tarefas
def get_task_creation_service(
    db: Session = Depends(get_db)
) -> TaskCreationService:
    return TaskCreationService(db=db)

# Função de dependência para o serviço de sincronização de squads
def get_squad_sync_service(
    db: Session = Depends(get_db),
    api_client: LegalOneApiClient = Depends(get_api_client)
) -> SquadSyncService:
    return SquadSyncService(db=db, api_client=api_client)

# ADICIONADO: Função de dependência para o serviço de orquestração
def get_orchestration_service(
    db: Session = Depends(get_db),
    squad_sync: SquadSyncService = Depends(get_squad_sync_service),
    task_creation: TaskCreationService = Depends(get_task_creation_service)
) -> OrchestrationService:
    return OrchestrationService(
        db=db,
        squad_sync_service=squad_sync,
        task_creation_service=task_creation
    )