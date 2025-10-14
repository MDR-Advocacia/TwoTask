# file: app/api/v1/endpoints/tasks.py


from openpyxl import load_workbook
from io import BytesIO
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Dict, Any
from app.core.dependencies import get_db, get_orchestration_service, get_batch_task_creation_service
from app.api.v1.schemas import TaskTriggerPayload, BatchTaskCreationRequest
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
from app.services.batch_task_creation_service import BatchTaskCreationService
from app.api.v1.schemas import BatchInteractiveCreationRequest, TaskCreationDataResponse
from app.core.dependencies import get_task_rule_service 
from app.services.task_rule_service import TaskRuleService
from app.api.v1.schemas import ValidatePublicationTasksRequest 

router = APIRouter()

class SpreadsheetRow(BaseModel):
    row_id: int
    data: Dict[str, Any]

class SpreadsheetAnalysisResponse(BaseModel):
    filename: str
    headers: List[str]
    rows: List[SpreadsheetRow]

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
    

@router.post("/batch-create", status_code=202, summary="Criar Tarefas em Lote a partir de uma Fonte Externa")
async def create_batch_tasks(
    request: BatchTaskCreationRequest,
    background_tasks: BackgroundTasks,
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service)
):
    """
    Recebe um lote de números de processo de uma fonte externa e inicia a criação
    de tarefas em segundo plano.

    - **fonte**: Identificador da aplicação de origem (ex: "Onesid").
    - **process_numbers**: Lista de CNJs para os quais as tarefas serão criadas.
    - **responsible_external_id**: ID externo do usuário do Legal One que será o responsável.
    """
    background_tasks.add_task(service.process_batch_request, request)
    return {"status": "recebido", "message": "A solicitação de criação de tarefas em lote foi recebida e está sendo processada em segundo plano."}

@router.post("/batch-create-from-spreadsheet", status_code=202, summary="Criar Tarefas em Lote a partir de uma Planilha")
async def create_batch_tasks_from_spreadsheet(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service)
):
    """
    Recebe um arquivo de planilha (.xlsx) e inicia a criação de tarefas
    em segundo plano com base em seu conteúdo.

    O arquivo deve ser enviado como 'multipart/form-data'.
    """
    # Validação do tipo de arquivo
    if not file.filename or not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Formato de arquivo inválido. Por favor, envie um arquivo .xlsx.")

    # Lê o conteúdo do arquivo em memória
    file_content = await file.read()

    # Adiciona a tarefa de processamento em segundo plano
    background_tasks.add_task(service.process_spreadsheet_request, file_content)
    
    return {"status": "recebido", "message": "A planilha foi recebida e está sendo processada em segundo plano."}

@router.post(
    "/analyze-spreadsheet",
    response_model=SpreadsheetAnalysisResponse,
    summary="Analisar Planilha para Criação de Tarefas Interativas"
)
async def analyze_spreadsheet(file: UploadFile = File(...)):
    """
    Recebe um arquivo .xlsx, extrai seu conteúdo (cabeçalhos e linhas)
    e o retorna como JSON para ser usado em uma interface de formulário interativo.
    """
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Formato de arquivo inválido. Por favor, envie um arquivo .xlsx.")

    try:
        content = await file.read()
        workbook = load_workbook(filename=BytesIO(content))
        sheet = workbook.active

        headers = [cell.value for cell in sheet[1]]
        
        rows_data = []
        for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            # Ignora linhas completamente vazias
            if not any(row):
                continue
            rows_data.append(SpreadsheetRow(row_id=index, data=dict(zip(headers, row))))

        return SpreadsheetAnalysisResponse(
            filename=file.filename,
            headers=headers,
            rows=rows_data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Não foi possível processar a planilha: {e}")


@router.post(
    "/batch-create-interactive",
    status_code=202,
    summary="Criar Tarefas em Lote a partir da Interface Interativa"
)
async def create_batch_tasks_interactive(
    request: BatchInteractiveCreationRequest, # <- Isto agora funciona!
    background_tasks: BackgroundTasks,
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service)
):
    """
    Recebe uma lista de tarefas pré-validadas pela interface interativa
    e inicia o processo de criação em segundo plano.
    """
    background_tasks.add_task(service.process_interactive_batch_request, request)
    
    return {"status": "recebido", "message": "A solicitação foi recebida e as tarefas estão sendo agendadas em segundo plano."}

@router.post(
    "/validate-publication-tasks",
    summary="Valida as regras de negócio para um conjunto de tarefas de uma publicação"
)
async def validate_publication_tasks(
    request: ValidatePublicationTasksRequest,
    rule_service: TaskRuleService = Depends(get_task_rule_service)
):
    """
    Recebe um conjunto de tarefas propostas para uma única publicação
    e verifica se elas atendem a todas as regras de co-ocorrência cadastradas.
    """
    try:
        # Pydantic já converteu o JSON para nossos objetos.
        # Agora, convertemos nossos objetos para dicionários, como o serviço espera.
        tasks_as_dicts = [task.model_dump(by_alias=True) for task in request.tasks]
        
        rule_service.validate_co_requisites(tasks_as_dicts)
        
        # Se nenhuma exceção foi levantada, as regras foram cumpridas.
        return {"status": "success", "message": "As regras de negócio foram atendidas."}
    
    except ValueError as e:
        # Se o serviço levantou um ValueError, significa que uma regra foi violada.
        # Retornamos um erro 422, que indica uma entidade não processável devido a erro de semântica.
        raise HTTPException(status_code=422, detail=str(e))
    
    except Exception as e:
        # Captura qualquer outro erro inesperado durante o processo.
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro inesperado durante a validação: {e}")
