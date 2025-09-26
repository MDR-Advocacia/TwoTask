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
    squad_ids: List[int]
    task_type_ids: List[int]

class ParentGroupNameUpdate(BaseModel):
    name: str

@router.post("/sync-metadata", status_code=202, summary="Sincronizar Metadados do Legal One")
async def sync_metadata(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Inicia o processo completo de sincronização de metadados do Legal One.
    """
    logger.info("Endpoint /sync-metadata chamado. Adicionando tarefa em background.")
    sync_service = MetadataSyncService(db_session=db)
    background_tasks.add_task(sync_service.sync_all_metadata)
    return {"message": "Processo de sincronização de metadados do Legal One iniciado em segundo plano."}

@router.get("/task-types", summary="Listar Tipos de Tarefa Agrupados")
def get_task_types_grouped(db: Session = Depends(get_db)):
    """
    Retorna uma lista de tipos de tarefa pai, com seus subtipos aninhados e squads associados.
    """
    parent_task_types = db.query(LegalOneTaskType).filter(LegalOneTaskType.parent_id.is_(None)).options(
        joinedload(LegalOneTaskType.sub_types).joinedload(LegalOneTaskType.squads)
    ).order_by(LegalOneTaskType.name).all()

    response_data = []
    for parent in parent_task_types:
        sub_types_data = []
        for sub_type in parent.sub_types:
            squad_ids = [squad.id for squad in sub_type.squads]
            sub_types_data.append({
                "id": sub_type.id,
                "name": sub_type.name,
                "squad_ids": squad_ids,
            })

        response_data.append({
            "parent_id": parent.id,
            "parent_name": parent.name,
            "sub_types": sub_types_data
        })

    return response_data

@router.post("/task-types/associate", summary="Associar Tipos de Tarefa a Squads")
def associate_task_types(payload: TaskTypeAssociationPayload, db: Session = Depends(get_db)):
    """
    Associa um grupo de subtipos de tarefa a uma lista de squads.
    """
    squads = db.query(Squad).filter(Squad.id.in_(payload.squad_ids)).all()
    if len(squads) != len(payload.squad_ids):
        raise HTTPException(status_code=404, detail="Um ou mais squads não foram encontrados.")

    task_types_to_process = db.query(LegalOneTaskType).filter(LegalOneTaskType.id.in_(payload.task_type_ids)).all()
    if not task_types_to_process:
        raise HTTPException(status_code=404, detail="Nenhum tipo de tarefa encontrado para associação.")

    parent_id = task_types_to_process[0].parent_id
    if not parent_id:
        raise HTTPException(status_code=400, detail="A associação só é permitida para subtipos de tarefa.")

    all_sub_types_in_group = db.query(LegalOneTaskType).filter(LegalOneTaskType.parent_id == parent_id).all()
    for task_type in all_sub_types_in_group:
        task_type.squads.clear()

    for task_type in task_types_to_process:
        task_type.squads.extend(squads)

    db.commit()
    return {"message": "Associação de tipos de tarefa atualizada com sucesso."}

@router.put("/task-parent-groups/{group_id}", summary="Renomear um Grupo de Tarefas Pai")
def rename_parent_task_group(group_id: int, payload: ParentGroupNameUpdate, db: Session = Depends(get_db)):
    """
    Atualiza o nome de um tipo de tarefa que é um pai.
    """
    parent_group = db.query(LegalOneTaskType).filter(
        LegalOneTaskType.id == group_id,
        LegalOneTaskType.parent_id.is_(None)
    ).first()

    if not parent_group:
        raise HTTPException(status_code=404, detail="Grupo de tarefas pai não encontrado.")

    parent_group.name = payload.name
    db.commit()
    db.refresh(parent_group)

    return {"id": parent_group.id, "name": parent_group.name}