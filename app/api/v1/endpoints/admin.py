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

        squad_id = task.squads[0].id if task.squads else None
        grouped_tasks[task.parent_id].append({
            "id": task.id,
            "name": task.name,
            "squad_id": squad_id
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