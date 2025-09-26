# app/api/v1/endpoints/admin.py

import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.core.dependencies import get_db
from app.services.metadata_sync_service import MetadataSyncService
from app.models.legal_one import LegalOneTaskType
from app.models.rules import Squad

router = APIRouter()
logger = logging.getLogger(__name__)

class TaskTypeAssociationPayload(BaseModel):
    squad_id: int
    task_type_ids: List[int]

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

# A rota /sync-squads e suas importações relacionadas foram removidas.
# A rota /update-member-link também foi removida, pois será recriada no endpoint de squads.

@router.get("/task-types", summary="Listar Tipos de Tarefa Agrupados")
def get_task_types_grouped(db: Session = Depends(get_db)):
    """
    Retorna uma lista de tipos de tarefa pai, com seus subtipos aninhados.
    Esta implementação é mais robusta, construindo a hierarquia manualmente
    para garantir que os dados sejam sempre processados corretamente.
    Um pai é identificado se `parent_id` é `NULL` ou se `parent_id` == `id`.
    """
    all_task_types = db.query(LegalOneTaskType).options(joinedload(LegalOneTaskType.squads)).all()

    parents = {}
    children_map = {}

    # Primeira passagem: separar pais e filhos
    for tt in all_task_types:
        # Um tipo de tarefa é um pai se seu parent_id for NULO ou igual ao seu próprio id
        if tt.parent_id is None or tt.parent_id == tt.id:
            parents[tt.id] = {
                "parent_id": tt.id,
                "parent_name": tt.name,
                "sub_types": []
            }
        else:
            # Este é um subtipo de tarefa
            if tt.parent_id not in children_map:
                children_map[tt.parent_id] = []

            squad_id = tt.squads[0].id if tt.squads else None
            children_map[tt.parent_id].append({
                "id": tt.id,
                "name": tt.name,
                "squad_id": squad_id
            })

    # Segunda passagem: anexar filhos aos pais
    for parent_id, parent_data in parents.items():
        if parent_id in children_map:
            # Ordena os subtipos alfabeticamente pelo nome
            parent_data["sub_types"] = sorted(children_map[parent_id], key=lambda x: x['name'])

    # Retorna a lista de pais, ordenada alfabeticamente pelo nome do pai
    return sorted(list(parents.values()), key=lambda x: x['parent_name'])

@router.post("/task-types/associate", summary="Associar Tipos de Tarefa a um Squad")
def associate_task_types(payload: TaskTypeAssociationPayload, db: Session = Depends(get_db)):
    """
    Associa um grupo de subtipos de tarefa (que compartilham o mesmo pai) a um squad específico.
    """
    squad = db.query(Squad).filter(Squad.id == payload.squad_id).first()
    if not squad:
        raise HTTPException(status_code=404, detail="Squad não encontrado.")

    task_types_to_associate = db.query(LegalOneTaskType).filter(LegalOneTaskType.id.in_(payload.task_type_ids)).all()
    if not task_types_to_associate:
        raise HTTPException(status_code=404, detail="Nenhum tipo de tarefa encontrado.")

    # Identificar o pai comum e todos os seus filhos
    parent_id = task_types_to_associate[0].parent_id
    if not parent_id:
        raise HTTPException(status_code=400, detail="A associação só é permitida para subtipos de tarefa.")

    all_sub_types = db.query(LegalOneTaskType).filter(LegalOneTaskType.parent_id == parent_id).all()

    # Remover associação existente *apenas para o squad alvo* em todo o grupo
    for task_type in all_sub_types:
        if squad in task_type.squads:
            task_type.squads.remove(squad)

    # Adicionar a nova associação
    for task_type in task_types_to_associate:
        if squad not in task_type.squads:
            task_type.squads.append(squad)

    db.commit()
    return {"message": "Associação de tipos de tarefa atualizada com sucesso."}