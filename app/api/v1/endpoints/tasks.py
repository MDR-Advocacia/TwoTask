# file: app/api/v1/endpoints/tasks.py

from openpyxl import load_workbook
from io import BytesIO
from typing import List, Dict, Any, Optional # <--- ADICIONADO Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File, Body # <--- ADICIONADO Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from datetime import datetime, timezone

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
from app.models.batch_execution import BatchExecution, BatchExecutionItem

router = APIRouter()

# --- NOVO SCHEMA PARA O RETRY INTELIGENTE ---
class RetryRequest(BaseModel):
    item_ids: Optional[List[int]] = None 

# --- SCHEMAS EXISTENTES ---
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
    class Config:
        from_attributes = True

class HierarchicalTaskTypeSchema(BaseModel):
    id: int
    name: str
    sub_types: List[SubTypeSchema]
    class Config:
        from_attributes = True

class UserForTaskForm(BaseModel):
    id: int
    external_id: int
    name: str
    squads: List[Dict[str, Any]]
    class Config:
        from_attributes = True

class OfficeForTaskForm(BaseModel):
    id: int
    external_id: int
    name: str
    class Config:
        from_attributes = True
    
class TaskCreationDataResponse(BaseModel):
    task_types: List[HierarchicalTaskTypeSchema]
    offices: List[OfficeForTaskForm]
    users: List[UserForTaskForm]
    task_statuses: List[Dict[str, Any]]


# --- ENDPOINTS ---

@router.get("/task-creation-data", response_model=TaskCreationDataResponse, summary="Obter dados para o formulário de criação de tarefas")
def get_data_for_task_form(db: Session = Depends(get_db)):
    """
    Fornece todos os dados necessários para popular os seletores no formulário de criação de tarefas.
    """
    task_types_query = db.query(LegalOneTaskType).options(
        joinedload(LegalOneTaskType.subtypes)
    ).order_by(LegalOneTaskType.name).all()

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

    offices = db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).order_by(LegalOneOffice.name).all()
    users = db.query(LegalOneUser)
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
    Recebe um lote de números de processo de uma fonte externa e inicia a criação.
    """
    background_tasks.add_task(service.process_batch_request, request)
    return {"status": "recebido", "message": "A solicitação de criação de tarefas em lote foi recebida e está sendo processada em segundo plano."}


@router.post("/batch-create-from-spreadsheet", status_code=202, summary="Criar Tarefas em Lote a partir de uma Planilha")
async def create_batch_tasks_from_spreadsheet(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
    db: Session = Depends(get_db) 
):
    """
    Recebe um arquivo de planilha (.xlsx), cria o registro de execução e inicia o processamento.
    """
    if not file.filename or not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Formato de arquivo inválido. Por favor, envie um arquivo .xlsx.")

    file_content = await file.read()

    execution_log = BatchExecution(
        source="Planilha",
        total_items=0, 
        start_time=datetime.now(timezone.utc)
    )
    db.add(execution_log)
    db.commit()
    db.refresh(execution_log)

    background_tasks.add_task(service.process_spreadsheet_request, file_content, execution_log.id)
    
    return {
        "status": "recebido", 
        "message": "Processamento iniciado em segundo plano.",
        "batch_id": execution_log.id
    }


@router.post(
    "/analyze-spreadsheet",
    response_model=SpreadsheetAnalysisResponse,
    summary="Analisar Planilha para Criação de Tarefas Interativas"
)
async def analyze_spreadsheet(file: UploadFile = File(...)):
    """
    Recebe um arquivo .xlsx, extrai seu conteúdo (cabeçalhos e linhas) e o retorna como JSON.
    """
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Formato de arquivo inválido. Por favor, envie um arquivo .xlsx.")

    try:
        content = await file.read()
        workbook = load_workbook(filename=BytesIO(content))
        sheet = workbook.active

        raw_headers = [cell.value for cell in sheet[1]]
        headers = [str(h).strip() if h is not None else '' for h in raw_headers]
        
        rows_data = []
        for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(row):
                continue
            
            cleaned_row = ["" if val is None else val for val in row]
            rows_data.append(SpreadsheetRow(row_id=index, data=dict(zip(headers, cleaned_row))))

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
    request: BatchInteractiveCreationRequest, 
    background_tasks: BackgroundTasks,
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service)
):
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
    try:
        tasks_as_dicts = [task.model_dump(by_alias=True) for task in request.tasks]
        rule_service.validate_co_requisites(tasks_as_dicts)
        return {"status": "success", "message": "As regras de negócio foram atendidas."}
    
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro inesperado durante a validação: {e}")

@router.get("/batch/status/{batch_id}", summary="Verificar progresso de um lote (Resumo)")
def get_batch_status(batch_id: int, db: Session = Depends(get_db)):
    """
    Retorna o status atual, contagem de itens processados e porcentagem de conclusão.
    """
    execution = db.query(BatchExecution).filter(BatchExecution.id == batch_id).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    processed_count = db.query(BatchExecutionItem).filter(
        BatchExecutionItem.execution_id == batch_id,
        BatchExecutionItem.status.in_([ "SUCESSO", "FALHA" ])
    ).count()

    total = execution.total_items or 0
    percentage = 0
    
    if total > 0:
        percentage = int((processed_count / total) * 100)
    
    status_str = "PROCESSANDO"
    if execution.end_time:
        status_str = "CONCLUIDO"
        percentage = 100
        processed_count = total

    return {
        "id": execution.id,
        "status": status_str,
        "total_items": total,
        "processed_items": processed_count,
        "percentage": percentage
    }

# --- NOVAS ROTAS PARA O RETRY INTELIGENTE ---

@router.get("/executions/{execution_id}", summary="Obter detalhes completos da execução")
async def get_execution_details(
    execution_id: int,
    db: Session = Depends(get_db)
):
    """
    Retorna o status da execução e a LISTA de itens (sucessos e falhas).
    Essencial para o frontend montar o agrupamento de erros.
    """
    execution = db.query(BatchExecution).options(
        joinedload(BatchExecution.items)
    ).filter(BatchExecution.id == execution_id).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    
    return execution

@router.post("/executions/{execution_id}/retry", summary="Reprocessar itens falhos")
async def retry_execution(
    execution_id: int,
    retry_data: Optional[RetryRequest] = Body(None), # Aceita filtro opcional de IDs
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Reprocessa itens falhos de um lote.
    - Se enviar JSON {"item_ids": [1, 2]}: Reprocessa só esses itens.
    - Se enviar vazio: Reprocessa TODOS os itens com falha.
    """
    client = LegalOneApiClient()
    service = BatchTaskCreationService(db, client)
    
    target_ids = retry_data.item_ids if retry_data else None

    background_tasks.add_task(
        service.retry_failed_items, 
        original_execution_id=execution_id,
        target_item_ids=target_ids
    )
    
    return {"message": "Reprocessamento iniciado em segundo plano."}