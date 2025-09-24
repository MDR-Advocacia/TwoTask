# app/api/v1/endpoints/admin.py

import logging
import asyncio
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.services.metadata_sync_service import MetadataSyncService
from app.services.squad_sync_service import SquadSyncService
from app.models.rules import SquadMember
from app.api.v1.schemas import SquadMemberLinkUpdate

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

@router.post("/update-member-link", response_class=HTMLResponse, summary="Associa um Membro de Squad a um Usuário do Legal One")
def update_member_link(
    link_data: SquadMemberLinkUpdate,
    db: Session = Depends(get_db)
):
    """
    Atualiza o vínculo entre um membro de squad (do sistema interno) e
    um usuário do Legal One. Retorna um fragmento HTML para HTMX.
    """
    logger.info(f"Recebida solicitação para vincular membro {link_data.squad_member_id} ao usuário L1 {link_data.legal_one_user_id}")
    
    member = db.query(SquadMember).filter(SquadMember.id == link_data.squad_member_id).first()
    
    if not member:
        return HTMLResponse('<span class="text-red-600 font-semibold">Erro: Membro do Squad não encontrado.</span>', status_code=404)

    # Converte o valor do dropdown para None se for 0 ou não existir
    member.legal_one_user_id = link_data.legal_one_user_id if link_data.legal_one_user_id else None
    
    db.commit()
    
    return HTMLResponse('<span class="text-green-600 font-semibold">Vínculo salvo com sucesso!</span>')