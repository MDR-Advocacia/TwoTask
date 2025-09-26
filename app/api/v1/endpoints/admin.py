# app/api/v1/endpoints/admin.py

import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.core.dependencies import get_db
from app.services.metadata_sync_service import MetadataSyncService
from app.models.legal_one import LegalOneTaskType
from app.models.task_group import TaskParentGroup
from app.models.rules import Squad

router = APIRouter()
logger = logging.getLogger(__name__)

class TaskTypeAssociationPayload(BaseModel):
    squad_ids: List[int]
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
    Retorna uma lista de tipos de tarefa agrupados pelo seu `parent_id`,
    utilizando a tabela `task_parent_groups` para obter os nomes dos grupos.
    """
    all_tasks = db.query(LegalOneTaskType).options(joinedload(LegalOneTaskType.squads)).all()
    parent_group_names = {group.id: group.name for group in db.query(TaskParentGroup).all()}

    grouped_tasks = {}

    for task in all_tasks:
        if not task.parent_id:
            continue

        if task.parent_id not in grouped_tasks:
            grouped_tasks[task.parent_id] = []

        squad_ids = [squad.id for squad in task.squads]
        grouped_tasks[task.parent_id].append({
            "id": task.id,
            "name": task.name,
            "squad_ids": squad_ids
        })

    response_data = []
    for parent_id, children in grouped_tasks.items():
        # Usa o nome customizado ou o ID como fallback, conforme solicitado
        parent_name = parent_group_names.get(parent_id, f"Grupo ID: {parent_id}")

        response_data.append({
            "parent_id": parent_id,
            "parent_name": parent_name,
            "sub_types": sorted(children, key=lambda x: x['name'])
        })

    return sorted(response_data, key=lambda x: x['parent_name'])

@router.post("/task-types/associate", summary="Associar Tipos de Tarefa a Squads")
def associate_task_types(payload: TaskTypeAssociationPayload, db: Session = Depends(get_db)):
    """
    Associa ou desassocia um grupo de subtipos de tarefa a um ou mais squads.
    A lógica agora é "replace all": todas as associações do grupo são removidas
    e as novas, da lista `squad_ids`, são adicionadas.
    """
    # Valida e busca os squads
    squads_to_associate = db.query(Squad).filter(Squad.id.in_(payload.squad_ids)).all()
    if len(squads_to_associate) != len(payload.squad_ids):
        raise HTTPException(status_code=404, detail="Um ou mais squads não foram encontrados.")

    # Valida e busca os tipos de tarefa (subtipos)
    task_types_in_group = db.query(LegalOneTaskType).filter(LegalOneTaskType.id.in_(payload.task_type_ids)).all()
    if not task_types_in_group:
        raise HTTPException(status_code=404, detail="Nenhum tipo de tarefa encontrado.")

    # Limpa todas as associações existentes para todas as tarefas no grupo
    for task_type in task_types_in_group:
        task_type.squads.clear()

    # Adiciona as novas associações
    if squads_to_associate:
        for task_type in task_types_in_group:
            task_type.squads.extend(squads_to_associate)

    db.commit()
    return {"message": "Associação de tipos de tarefa atualizada com sucesso."}

class TaskParentGroupUpdatePayload(BaseModel):
    name: str

@router.put("/task-parent-groups/{parent_id}", summary="Renomear ou Criar um Grupo de Tarefas Pai")
def upsert_task_parent_group(
    parent_id: int,
    payload: TaskParentGroupUpdatePayload,
    db: Session = Depends(get_db)
):
    """
    Atualiza o nome de um grupo de tarefas pai existente ou cria um novo.
    """
    parent_group = db.query(TaskParentGroup).filter(TaskParentGroup.id == parent_id).first()

    if parent_group:
        parent_group.name = payload.name
    else:
        parent_group = TaskParentGroup(id=parent_id, name=payload.name)
        db.add(parent_group)

    db.commit()
    db.refresh(parent_group)

    return {"id": parent_group.id, "name": parent_group.name}