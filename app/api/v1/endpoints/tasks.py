# file: app/api/v1/endpoints/tasks.py

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.api.v1.schemas import TaskTriggerPayload
from app.services.orchestration_service import OrchestrationService, ProcessNotFoundError, MissingResponsibleUserError
from app.core.dependencies import get_orchestration_service
from app.services.task_creation_service import (
    TaskCreationService,
    TaskCreationRequest,
    LawsuitNotFoundError,
    TaskCreationError,
    TaskLinkingError,
)
from app.services.legal_one_client import LegalOneApiClient
from app.models.legal_one import LegalOneTaskType, LegalOneUser
from app.models.rules import Squad, SquadMember
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import joinedload
from sqlalchemy import or_

# --- Pydantic Schemas for the new endpoint ---
class UserSquadInfo(BaseModel):
    id: int
    name: str

class UserForTaskForm(BaseModel):
    id: int # User ID in our DB
    external_id: int # User ID in Legal One
    name: str
    squads: List[UserSquadInfo]

    class Config:
        orm_mode = True

class TaskSubTypeForForm(BaseModel):
    id: int
    name: str
    parentTypeId: int
    squad_ids: List[int]

    class Config:
        orm_mode = True

class TaskTypeForForm(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True

class TaskCreationDataResponse(BaseModel):
    task_types: List[TaskTypeForForm]
    sub_types: List[TaskSubTypeForForm]
    users: List[UserForTaskForm]


# O APIRouter funciona como um "mini-aplicativo" para agrupar endpoints relacionados.
router = APIRouter()


from app.models.task_group import TaskParentGroup

@router.get("/task-creation-data", response_model=TaskCreationDataResponse, summary="Obter dados para o formulário de criação de tarefas")
def get_data_for_task_form(db: Session = Depends(get_db)):
    """
    Endpoint otimizado para fornecer todos os dados necessários para a página de criação de tarefas,
    utilizando a tabela de mapeamento de grupos.
    """
    # 1. Buscar os nomes dos grupos pai da tabela de mapeamento.
    parent_groups = db.query(TaskParentGroup).order_by(TaskParentGroup.name).all()
    parent_group_ids = {pg.id for pg in parent_groups}

    # 2. Buscar todos os subtipos de tarefa que pertencem a esses grupos.
    all_sub_types = db.query(LegalOneTaskType).filter(
        LegalOneTaskType.parent_id.in_(parent_group_ids)
    ).options(
        joinedload(LegalOneTaskType.squads)
    ).all()

    sub_types_for_form = [
        TaskSubTypeForForm(
            id=st.id,
            name=st.name,
            parentTypeId=st.parent_id,
            squad_ids=[squad.id for squad in st.squads]
        ) for st in all_sub_types if st.parent_id is not None
    ]

    # 3. Buscar Usuários ativos com seus squads (lógica inalterada).
    users_query = db.query(LegalOneUser).filter(LegalOneUser.is_active == True).options(
        joinedload(LegalOneUser.squad_members).joinedload(SquadMember.squad)
    ).all()

    users_for_form = []
    for user in users_query:
        squads = [
            UserSquadInfo(id=member.squad.id, name=member.squad.name)
            for member in user.squad_members if member.squad.is_active
        ]
        users_for_form.append(
            UserForTaskForm(
                id=user.id,
                external_id=user.external_id,
                name=user.name,
                squads=squads
            )
        )

    # Mapeia os grupos para o formato de resposta TaskTypeForForm
    task_types_for_form = [TaskTypeForForm(id=pg.id, name=pg.name) for pg in parent_groups]

    return TaskCreationDataResponse(
        task_types=task_types_for_form,
        sub_types=sub_types_for_form,
        users=users_for_form
    )

@router.post("/trigger/task", tags=["Tasks"])
def trigger_task_creation(
    payload: TaskTriggerPayload,
    orchestrator: OrchestrationService = Depends(get_orchestration_service)
):
    """
    Recebe um gatilho para iniciar o processo de criação de uma tarefa.

    Este endpoint irá:
    1. Validar o payload de entrada.
    2. Chamar o serviço de orquestração para enriquecer os dados e aplicar a lógica de negócio.
    3. Retornar o resultado da criação da tarefa.
    """
    try:
        result = orchestrator.handle_task_trigger(payload)
        return JSONResponse(
            status_code=201, # 201 Created é o status ideal para sucesso em uma criação
            content=result
        )
    except ProcessNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except MissingResponsibleUserError as e:
        # Erro de negócio que impede a continuação
        raise HTTPException(
            status_code=422, # Unprocessable Entity
            detail=str(e)
        )
    except Exception as e:
        # Captura qualquer outro erro inesperado
        raise HTTPException(
            status_code=500,
            detail=f"Ocorreu um erro interno inesperado: {str(e)}"
        )

@router.get("/search-lawsuit", summary="Buscar Processo por CNJ no Legal One", tags=["Tasks"])
def search_lawsuit(
    cnj: str = Query(..., description="Número CNJ a ser pesquisado."),
    # Injeção de dependência direta do cliente, pois é uma chamada simples
    legal_one_client: LegalOneApiClient = Depends(LegalOneApiClient)
):
    """
    Busca um processo no Legal One usando o número CNJ fornecido.
    """
    lawsuit = legal_one_client.search_lawsuit_by_cnj(cnj)
    if not lawsuit:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum processo encontrado para o CNJ: {cnj}"
        )
    
    return lawsuit

@router.post("/create-full-process", summary="Criar Tarefa (Processo Completo)", tags=["Tasks"])
def create_full_task(
    request: TaskCreationRequest,
    db: Session = Depends(get_db)
):
    """
    Endpoint para orquestrar a criação completa de uma tarefa no Legal One.
    1. Busca o processo pelo CNJ.
    2. Cria a tarefa.
    3. Vincula a tarefa ao processo.
    4. Adiciona os participantes.
    """
    task_service = TaskCreationService(db)
    try:
        result = task_service.create_full_task_process(request)
        return JSONResponse(
            status_code=201,
            content=result
        )
    except LawsuitNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (TaskCreationError, TaskLinkingError) as e:
        # Erros de negócio que resultam em falha na operação
        raise HTTPException(status_code=422, detail=str(e)) # Unprocessable Entity
    except Exception as e:
        # Erro genérico para problemas inesperados
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro interno inesperado: {str(e)}")