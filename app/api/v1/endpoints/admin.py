import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_batch_task_creation_service, get_db
from app.models.legal_one import LegalOneTaskType
from app.models.rules import Squad
from app.models.task_group import TaskParentGroup
from app.services.batch_task_creation_service import BatchTaskCreationService
from app.services.metadata_sync_service import run_metadata_sync_job

router = APIRouter()
logger = logging.getLogger(__name__)


class TaskSubTypeSchema(BaseModel):
    id: int
    name: str
    squad_ids: List[int]


class TaskTypeGroupSchema(BaseModel):
    parent_id: int
    parent_name: str
    sub_types: List[TaskSubTypeSchema]


class TaskTypeAssociationPayload(BaseModel):
    squad_ids: List[int]
    task_type_ids: List[int]


class TaskParentGroupUpdatePayload(BaseModel):
    name: str


@router.post("/sync-metadata", status_code=202, summary="Sincronizar metadados do Legal One", tags=["Admin"])
async def sync_metadata(
    background_tasks: BackgroundTasks,
):
    logger.info("Endpoint /sync-metadata chamado. Adicionando tarefa em background.")
    background_tasks.add_task(run_metadata_sync_job)
    return {"message": "Processo de sincronizacao de metadados do Legal One iniciado em segundo plano."}


@router.get(
    "/task-types",
    summary="Listar tipos de tarefa agrupados",
    tags=["Admin"],
    response_model=List[TaskTypeGroupSchema],
)
def get_task_types_grouped(db: Session = Depends(get_db)):
    task_types = db.query(LegalOneTaskType).options(
        joinedload(LegalOneTaskType.subtypes),
        joinedload(LegalOneTaskType.squads),
    ).order_by(LegalOneTaskType.name).all()
    custom_group_names = {group.id: group.name for group in db.query(TaskParentGroup).all()}

    response_data = []
    for task_type in task_types:
        squad_ids = [squad.id for squad in task_type.squads]
        sub_types_data = [
            TaskSubTypeSchema(
                id=sub_type.id,
                name=sub_type.name,
                squad_ids=squad_ids,
            )
            for sub_type in sorted(task_type.subtypes, key=lambda item: item.name)
        ]

        response_data.append(
            TaskTypeGroupSchema(
                parent_id=task_type.id,
                parent_name=custom_group_names.get(task_type.id, task_type.name),
                sub_types=sub_types_data,
            )
        )

    return response_data


@router.put("/task-parent-groups/{parent_id}", summary="Renomear grupo pai de tarefas", tags=["Admin"])
def update_task_parent_group(
    parent_id: int,
    payload: TaskParentGroupUpdatePayload,
    db: Session = Depends(get_db),
):
    task_type = db.query(LegalOneTaskType).filter(LegalOneTaskType.id == parent_id).first()
    if not task_type:
        raise HTTPException(status_code=404, detail="Grupo de tarefa nao encontrado.")

    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="O nome do grupo nao pode ficar vazio.")

    group = db.query(TaskParentGroup).filter(TaskParentGroup.id == parent_id).first()
    if group is None:
        group = TaskParentGroup(id=parent_id, name=normalized_name)
        db.add(group)
    else:
        group.name = normalized_name

    db.commit()
    db.refresh(group)
    return {"id": group.id, "name": group.name}


@router.post("/task-types/associate", summary="Associar tipos de tarefa a squads", tags=["Admin"])
def associate_task_types(payload: TaskTypeAssociationPayload, db: Session = Depends(get_db)):
    squads = db.query(Squad).filter(Squad.id.in_(payload.squad_ids)).all()
    if len(squads) != len(set(payload.squad_ids)):
        raise HTTPException(status_code=404, detail="Um ou mais squads nao foram encontrados.")

    task_types = db.query(LegalOneTaskType).filter(LegalOneTaskType.id.in_(payload.task_type_ids)).all()
    if len(task_types) != len(set(payload.task_type_ids)):
        raise HTTPException(status_code=404, detail="Um ou mais tipos de tarefa nao foram encontrados.")

    for task_type in task_types:
        task_type.squads = squads

    db.commit()
    return {"message": "Associacao de tipos de tarefa atualizada com sucesso."}


@router.post(
    "/batch-executions/{execution_id}/retry",
    status_code=202,
    summary="Reprocessar itens falhos de um lote",
    tags=["Admin"],
)
async def retry_failed_batch_items(
    execution_id: int,
    background_tasks: BackgroundTasks,
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
):
    logger.info("Recebida solicitacao para reprocessar falhas do lote ID: %s", execution_id)
    background_tasks.add_task(service.retry_failed_items, execution_id)
    return {"message": f"Reprocessamento para o lote {execution_id} iniciado em segundo plano."}
