# file: app/api/v1/endpoints/tasks.py

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Dict, Any

from app.core.dependencies import get_db, get_orchestration_service
from app.api.v1.schemas import TaskTriggerPayload
from app.services.orchestration_service import OrchestrationService, ProcessNotFoundError, MissingResponsibleUserError
from app.services.task_creation_service import (
    TaskCreationService,
    TaskCreationRequest,
    LawsuitNotFoundError,
    TaskCreationError,
    TaskLinkingError,
    InvalidDataError
)
from app.services.legal_one_client import LegalOneApiClient
from app.models.legal_one import LegalOneOffice, LegalOneUser, LegalOneTaskType, LegalOneTaskSubType
from app.models.rules import Squad, SquadMember

router = APIRouter()

# --- Schemas Pydantic (ajustados para a nova estrutura de dados) ---
class SubTypeSchema(BaseModel):
    id: int
    name: str

class HierarchicalTaskTypeSchema(BaseModel):
    id: int
    name: str
    sub_types: List[SubTypeSchema]

class UserForTaskForm(BaseModel):
    id: int
    external_id: int
    name: str
    squads: List[Dict[str, Any]]

class OfficeForTaskForm(BaseModel):
    id: int
    external_id: int
    name: str
    
class TaskCreationDataResponse(BaseModel):
    task_types: List[HierarchicalTaskTypeSchema]
    offices: List[OfficeForTaskForm]
    users: List[UserForTaskForm]
    task_statuses: List[Dict[str, Any]]


# --- ENDPOINT CORRIGIDO (SEM FILTRO DE USUÁRIO) ---
@router.get("/task-creation-data", response_model=TaskCreationDataResponse, summary="Obter dados para o formulário de criação de tarefas")
def get_data_for_task_form(db: Session = Depends(get_db)):
    """
    Fornece todos os dados necessários para popular os seletores no formulário de criação de tarefas.
    """
    # 1. Buscar TODOS os Tipos de Tarefa (pais) e seus subtipos.
    task_types_query = db.query(LegalOneTaskType).options(
        joinedload(LegalOneTaskType.subtypes)
    ).order_by(LegalOneTaskType.name).all()

    # 2. Formatar a resposta hierárquica
    formatted_task_types = [
        HierarchicalTaskTypeSchema(
            id=parent.id,
            name=parent.name,
            sub_types=[
                SubTypeSchema(id=sub.id, name=sub.name)
                for sub in sorted(parent.subtypes, key=lambda x: x.name)
            ]
        ) for parent in task_types_query
    ]

    # 3. Buscar os outros dados (lógica original preservada)
    offices = db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).order_by(LegalOneOffice.name).all()
    users = db.query(LegalOneUser).filter(LegalOneUser.is_active == True).options(
        joinedload(LegalOneUser.squad_members).joinedload(SquadMember.squad)
    ).all()
    users_for_form = [
        UserForTaskForm(
            id=user.id,
            external_id=user.external_id,
            name=user.name,
            squads=[{"id": member.squad.id, "name": member.squad.name} for member in user.squad_members]
        ) for user in users
    ]
    task_statuses = [
        {"id": 0, "name": "Pendente"}, {"id": 1, "name": "Cumprido"}, {"id": 2, "name": "Não cumprido"}, {"id": 3, "name": "Cancelado"}
    ]

    return TaskCreationDataResponse(
        task_types=formatted_task_types,
        offices=[OfficeForTaskForm(id=o.id, name=o.name, external_id=o.external_id) for o in offices],
        users=users_for_form,
        task_statuses=task_statuses
    )

# --- ENDPOINTS ORIGINAIS 100% PRESERVADOS ---

@router.post("/trigger/task", tags=["Tasks"])
def trigger_task_creation(
    payload: TaskTriggerPayload,
    orchestrator: OrchestrationService = Depends(get_orchestration_service)
):
    try:
        result = orchestrator.handle_task_trigger(payload)
        return JSONResponse(status_code=201, content=result)
    except ProcessNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MissingResponsibleUserError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro interno inesperado: {str(e)}")


@router.get("/search-lawsuit", summary="Buscar Processo por CNJ no Legal One", tags=["Tasks"])
def search_lawsuit(
    cnj: str = Query(..., description="Número CNJ a ser pesquisado."),
    legal_one_client: LegalOneApiClient = Depends(LegalOneApiClient)
):
    lawsuit = legal_one_client.search_lawsuit_by_cnj(cnj)
    if not lawsuit:
        raise HTTPException(status_code=404, detail=f"Nenhum processo encontrado para o CNJ: {cnj}")
    return lawsuit


@router.post("/create-full-process", summary="Criar Tarefa (Processo Completo)", tags=["Tasks"])
def create_full_task(
    request: TaskCreationRequest,
    db: Session = Depends(get_db)
):
    task_service = TaskCreationService(db)
    try:
        result = task_service.create_full_task_process(request)
        return JSONResponse(status_code=201, content=result)
    except LawsuitNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidDataError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (TaskCreationError, TaskLinkingError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro interno inesperado: {str(e)}")