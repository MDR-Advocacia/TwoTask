# app/api/v1/endpoints/admin.py

import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List

from app.core.dependencies import get_db
from app.services.metadata_sync_service import MetadataSyncService
from app.models.legal_one import LegalOneTaskType, LegalOneTaskSubType
from app.models.rules import Squad
# A importação de TaskParentGroup foi removida por ser obsoleta

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Schemas Pydantic para clareza da resposta ---
# (Estes devem corresponder ou ser movidos para o seu arquivo de schemas)

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
    # O nome foi mantido, mas agora estes são os IDs dos Tipos de Tarefa (pais)
    task_type_ids: List[int]

# --- Endpoints ---

@router.post("/sync-metadata", status_code=202, summary="Sincronizar Metadados do Legal One", tags=["Admin"])
async def sync_metadata(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Inicia o processo completo de sincronização de metadados do Legal One.
    """
    logger.info("Endpoint /sync-metadata chamado. Adicionando tarefa em background.")
    sync_service = MetadataSyncService(db=db)
    background_tasks.add_task(sync_service.sync_all_metadata)
    return {"message": "Processo de sincronização de metadados do Legal One iniciado em segundo plano."}


@router.get("/task-types", summary="Listar Tipos de Tarefa Agrupados", tags=["Admin"], response_model=List[TaskTypeGroupSchema])
def get_task_types_grouped(db: Session = Depends(get_db)):
    """
    Retorna uma lista de tipos de tarefa, com seus subtipos aninhados e squads associados.
    A lógica foi refatorada para usar a nova estrutura de dados hierárquica.
    """
    # Usamos joinedload para buscar os tipos, seus subtipos e os squads associados
    # em consultas otimizadas, evitando o problema N+1.
    task_types = db.query(LegalOneTaskType).options(
        joinedload(LegalOneTaskType.subtypes),
        joinedload(LegalOneTaskType.squads)
    ).order_by(LegalOneTaskType.name).all()

    response_data = []
    for task_type in task_types:
        squad_ids = [squad.id for squad in task_type.squads]
        
        sub_types_data = [
            TaskSubTypeSchema(
                id=sub_type.id,
                name=sub_type.name,
                squad_ids=squad_ids  # Os squads são do tipo pai
            ) for sub_type in sorted(task_type.subtypes, key=lambda x: x.name)
        ]
        
        response_data.append(
            TaskTypeGroupSchema(
                parent_id=task_type.id,
                parent_name=task_type.name,
                sub_types=sub_types_data
            )
        )
        
    return response_data


@router.post("/task-types/associate", summary="Associar Tipos de Tarefa a Squads", tags=["Admin"])
def associate_task_types(payload: TaskTypeAssociationPayload, db: Session = Depends(get_db)):
    """
    Associa uma lista de Tipos de Tarefa (pais) a uma lista de squads.
    A lógica foi atualizada para refletir o novo modelo, onde a associação é feita no tipo pai.
    """
    squads = db.query(Squad).filter(Squad.id.in_(payload.squad_ids)).all()
    if len(squads) != len(set(payload.squad_ids)):
        raise HTTPException(status_code=404, detail="Um ou mais squads não foram encontrados.")

    task_types = db.query(LegalOneTaskType).filter(LegalOneTaskType.id.in_(payload.task_type_ids)).all()
    if len(task_types) != len(set(payload.task_type_ids)):
        raise HTTPException(status_code=404, detail="Um ou mais tipos de tarefa não foram encontrados.")

    for task_type in task_types:
        # A associação agora é direta: define a lista de squads para cada tipo de tarefa.
        task_type.squads = squads
            
    db.commit()
    return {"message": "Associação de tipos de tarefa atualizada com sucesso."}

# O endpoint abaixo foi comentado pois a tabela `task_parent_groups` foi removida
# na nova arquitetura. O nome do grupo agora é o próprio nome do `LegalOneTaskType`,
# que é sincronizado diretamente do Legal One e não deve ser editado manualmente.

# @router.put("/task-parent-groups/{group_id}", summary="Renomear um Grupo de Tarefas Pai", tags=["Admin"])
# def rename_parent_task_group(group_id: int, payload: ParentGroupNameUpdate, db: Session = Depends(get_db)):
#     # ... implementação antiga ...
#     pass