# Conteúdo COMPLETO e ATUALIZADO para: app/api/v1/endpoints/admin.py

import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.services.metadata_sync_service import MetadataSyncService
from app.services.squad_sync_service import SquadSyncService # NOVO IMPORT

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/sync-metadata", status_code=202, summary="Sincronizar Metadados do Legal One")
async def sync_metadata(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Inicia o processo completo de sincronização de metadados do Legal One.
    Isso inclui escritórios, tipos de tarefa e usuários.
    A operação é executada em segundo plano.
    """
    logger.info("Endpoint /sync-metadata chamado. Adicionando tarefa em background.")
    sync_service = MetadataSyncService(db_session=db)
    background_tasks.add_task(sync_service.sync_all_metadata)
    return {"message": "Processo de sincronização de metadados do Legal One iniciado em segundo plano."}

# --- NOVO ENDPOINT ADICIONADO AQUI ---
@router.post("/sync-squads", status_code=202, summary="Sincronizar Squads da API Interna")
async def sync_squads(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Dispara a sincronização da estrutura de squads e membros a partir da API interna.
    
    Este processo irá:
    - Buscar os dados mais recentes da SQUADS_API_URL.
    - Adicionar novos squads e membros.
    - Atualizar os dados de squads e membros existentes.
    - Desativar squads e membros que não estão mais presentes na API.
    
    A operação é executada em segundo plano para não bloquear a resposta.
    """
    logger.info("Endpoint /sync-squads chamado. Adicionando tarefa de sincronização de squads em background.")
    squad_sync_service = SquadSyncService(db_session=db)
    background_tasks.add_task(squad_sync_service.sync_squads)
    
    return {"message": "Processo de sincronização de squads iniciado em segundo plano."}