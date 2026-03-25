import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.api.v1.schemas import (
    BatchInteractiveCreationRequest,
    BatchTaskCreationRequest,
    TaskTriggerPayload,
    ValidatePublicationTasksRequest,
)
from app.core import auth as auth_security
from app.core.config import settings
from app.core.dependencies import (
    get_api_client,
    get_batch_task_creation_service,
    get_db,
    get_orchestration_service,
    get_task_rule_service,
)
from app.core.uploads import validate_spreadsheet_file_metadata
from app.models.batch_execution import (
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_COMPLETED,
    BATCH_STATUS_COMPLETED_WITH_ERRORS,
    BATCH_STATUS_PAUSED,
    BATCH_STATUS_PENDING,
    BATCH_STATUS_PROCESSING,
    BatchExecution,
    BatchExecutionItem,
)
from app.models.legal_one import LegalOneOffice, LegalOneTaskType, LegalOneUser
from app.services.batch_strategies.spreadsheet_strategy import SpreadsheetStrategy
from app.services.batch_task_creation_service import BatchTaskCreationService
from app.services.legal_one_client import LegalOneApiClient
from app.services.orchestration_service import (
    MissingResponsibleUserError,
    OrchestrationService,
    ProcessNotFoundError,
)
from app.services.task_creation_service import (
    InvalidDataError,
    LawsuitNotFoundError,
    TaskCreationError,
    TaskCreationRequest,
    TaskCreationService,
    TaskLinkingError,
)
from app.services.task_rule_service import TaskRuleService

router = APIRouter()


class RetryRequest(BaseModel):
    item_ids: Optional[List[int]] = None


class SpreadsheetRow(BaseModel):
    row_id: int
    data: Dict[str, Any]


class SpreadsheetAnalysisResponse(BaseModel):
    filename: str
    headers: List[str]
    rows: List[SpreadsheetRow]


class SpreadsheetPreviewRow(BaseModel):
    row_id: int
    process_number: Optional[str] = None
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    fingerprint: Optional[str] = None
    data: Dict[str, Any]


class SpreadsheetPreviewSummary(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows_in_file: int
    duplicate_rows_in_history: int


class SpreadsheetPreviewResponse(BaseModel):
    filename: str
    headers: List[str]
    summary: SpreadsheetPreviewSummary
    rows: List[SpreadsheetPreviewRow]


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


def _validate_spreadsheet_upload(file: UploadFile, file_content: bytes) -> None:
    validate_spreadsheet_file_metadata(
        file.filename,
        file.content_type,
        len(file_content),
        max_size_bytes=settings.spreadsheet_max_size_bytes,
        allowed_content_types=settings.allowed_spreadsheet_content_types,
    )


def _build_template_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Agendamentos"
    headers = [
        "ESCRITORIO",
        "CNJ",
        "PUBLISH_DATE",
        "SUBTIPO",
        "EXECUTANTE",
        "PRAZO",
        "DATA_TAREFA",
        "HORARIO",
        "OBSERVACAO",
        "DESCRICAO",
    ]
    sheet.append(headers)
    sheet.append(
        [
            "Juridico / Filial SP / Contencioso",
            "0000000-00.2026.8.00.0000",
            "18/03/2026",
            "Audiencia",
            "Maria Silva",
            "25/03/2026",
            "25/03/2026",
            "14:00",
            "Observacoes opcionais",
            "Complemento opcional",
        ]
    )

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _build_error_report_csv(items: list[BatchExecutionItem]) -> str:
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["item_id", "cnj", "status", "task_id", "erro"])
    for item in items:
        writer.writerow(
            [
                item.id,
                item.process_number,
                item.status,
                item.created_task_id or "",
                item.error_message or "",
            ]
        )
    return stream.getvalue()


@router.get(
    "/task-creation-data",
    response_model=TaskCreationDataResponse,
    summary="Obter dados para o formulario de criacao de tarefas",
)
def get_data_for_task_form(db: Session = Depends(get_db)):
    task_types_query = (
        db.query(LegalOneTaskType)
        .options(joinedload(LegalOneTaskType.subtypes))
        .order_by(LegalOneTaskType.name)
        .all()
    )
    formatted_task_types = [
        HierarchicalTaskTypeSchema(
            id=parent.id,
            name=parent.name,
            sub_types=[
                SubTypeSchema(id=sub.id, name=sub.name)
                for sub in sorted(parent.subtypes, key=lambda item: item.name)
            ],
        )
        for parent in task_types_query
    ]

    offices = (
        db.query(LegalOneOffice)
        .filter(LegalOneOffice.is_active == True)
        .order_by(LegalOneOffice.name)
        .all()
    )
    users = db.query(LegalOneUser)
    users_for_form = [
        UserForTaskForm(
            id=user.id,
            external_id=user.external_id,
            name=user.name,
            squads=[{"id": member.squad.id, "name": member.squad.name} for member in user.squad_members],
        )
        for user in users
    ]
    task_statuses = [
        {"id": 0, "name": "Pendente"},
        {"id": 1, "name": "Cumprido"},
        {"id": 2, "name": "Nao cumprido"},
        {"id": 3, "name": "Cancelado"},
    ]

    return TaskCreationDataResponse(
        task_types=formatted_task_types,
        offices=[OfficeForTaskForm(id=office.id, name=office.name, external_id=office.external_id) for office in offices],
        users=users_for_form,
        task_statuses=task_statuses,
    )


@router.get("/spreadsheet-template", summary="Baixar modelo oficial da planilha")
def download_spreadsheet_template():
    return StreamingResponse(
        BytesIO(_build_template_bytes()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="modelo_agendamento_planilha.xlsx"'},
    )


@router.post(
    "/preview-spreadsheet",
    response_model=SpreadsheetPreviewResponse,
    summary="Pre-validar planilha antes do agendamento",
)
async def preview_spreadsheet(
    file: UploadFile = File(...),
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
):
    file_content = await file.read()
    try:
        _validate_spreadsheet_upload(file, file_content)
        strategy = SpreadsheetStrategy(service.db, service.client)
        preview = await strategy.build_preview(file_content)
        return SpreadsheetPreviewResponse(
            filename=file.filename or "planilha.xlsx",
            headers=preview["headers"],
            summary=SpreadsheetPreviewSummary(**preview["summary"]),
            rows=[SpreadsheetPreviewRow(**row) for row in preview["rows"]],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/trigger/task", tags=["Tasks"])
def trigger_task_creation(
    payload: TaskTriggerPayload,
    orchestrator: OrchestrationService = Depends(get_orchestration_service),
):
    try:
        result = orchestrator.handle_task_trigger(payload)
        return JSONResponse(status_code=201, content=result)
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingResponsibleUserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro interno inesperado: {exc}") from exc


@router.get("/search-lawsuit", summary="Buscar processo por CNJ no Legal One", tags=["Tasks"])
def search_lawsuit(
    cnj: str = Query(..., description="Numero CNJ a ser pesquisado."),
    legal_one_client: LegalOneApiClient = Depends(get_api_client),
):
    lawsuit = legal_one_client.search_lawsuit_by_cnj(cnj)
    if not lawsuit:
        raise HTTPException(status_code=404, detail=f"Nenhum processo encontrado para o CNJ: {cnj}")
    return lawsuit


@router.post("/create-full-process", summary="Criar tarefa (processo completo)", tags=["Tasks"])
def create_full_task(
    request: TaskCreationRequest,
    db: Session = Depends(get_db),
):
    task_service = TaskCreationService(db)
    try:
        result = task_service.create_full_task_process(request)
        return JSONResponse(status_code=201, content=result)
    except LawsuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (TaskCreationError, TaskLinkingError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro interno inesperado: {exc}") from exc


@router.post(
    "/batch-create",
    status_code=202,
    summary="Criar tarefas em lote a partir de uma fonte externa",
)
async def create_batch_tasks(
    request: BatchTaskCreationRequest,
    background_tasks: BackgroundTasks,
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
):
    background_tasks.add_task(service.process_batch_request, request)
    return {
        "status": "recebido",
        "message": "A solicitacao de criacao de tarefas em lote foi recebida e esta sendo processada em segundo plano.",
    }


@router.post(
    "/batch-create-from-spreadsheet",
    status_code=202,
    summary="Criar tarefas em lote a partir de uma planilha",
)
async def create_batch_tasks_from_spreadsheet(
    file: UploadFile = File(...),
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    file_content = await file.read()

    try:
        _validate_spreadsheet_upload(file, file_content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        execution_log = service.create_spreadsheet_execution(
            file_content=file_content,
            source_filename=file.filename,
            requested_by_email=current_user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": execution_log.status,
        "message": "Lote recebido e colocado na fila de processamento.",
        "batch_id": execution_log.id,
    }


@router.post(
    "/analyze-spreadsheet",
    response_model=SpreadsheetAnalysisResponse,
    summary="Analisar planilha para criacao de tarefas interativas",
)
async def analyze_spreadsheet(file: UploadFile = File(...)):
    workbook = None
    try:
        content = await file.read()
        _validate_spreadsheet_upload(file, content)

        workbook = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        raw_headers = [cell.value for cell in sheet[1]]
        headers = [str(header).strip() if header is not None else "" for header in raw_headers]

        rows_data = []
        for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(value not in (None, "") and str(value).strip() for value in row):
                continue
            cleaned_row = ["" if value is None else value for value in row]
            rows_data.append(SpreadsheetRow(row_id=index, data=dict(zip(headers, cleaned_row))))

        return SpreadsheetAnalysisResponse(
            filename=file.filename or "planilha.xlsx",
            headers=headers,
            rows=rows_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Nao foi possivel processar a planilha: {exc}") from exc
    finally:
        if workbook is not None:
            workbook.close()


@router.post(
    "/batch-create-interactive",
    status_code=202,
    summary="Criar tarefas em lote a partir da interface interativa",
)
async def create_batch_tasks_interactive(
    request: BatchInteractiveCreationRequest,
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    execution_log = service.create_interactive_execution(
        request,
        requested_by_email=current_user.email,
    )
    return {
        "status": execution_log.status,
        "message": "A solicitacao foi recebida e entrou na fila de agendamento.",
        "batch_id": execution_log.id,
    }


@router.post(
    "/validate-publication-tasks",
    summary="Validar regras de negocio para um conjunto de tarefas de uma publicacao",
)
async def validate_publication_tasks(
    request: ValidatePublicationTasksRequest,
    rule_service: TaskRuleService = Depends(get_task_rule_service),
):
    try:
        tasks_as_dicts = [task.model_dump(by_alias=True) for task in request.tasks]
        rule_service.validate_co_requisites(tasks_as_dicts)
        return {"status": "success", "message": "As regras de negocio foram atendidas."}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro inesperado durante a validacao: {exc}") from exc


@router.get("/batch/status/{batch_id}", summary="Verificar progresso de um lote (resumo)")
def get_batch_status(batch_id: int, db: Session = Depends(get_db)):
    execution = db.query(BatchExecution).filter(BatchExecution.id == batch_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Lote nao encontrado")

    processed_count = (
        db.query(BatchExecutionItem)
        .filter(
            BatchExecutionItem.execution_id == batch_id,
            BatchExecutionItem.status.in_(["SUCESSO", "FALHA"]),
        )
        .count()
    )

    total = execution.total_items or 0
    percentage = int((processed_count / total) * 100) if total > 0 else 0
    remaining_items = max(0, total - processed_count)

    return {
        "id": execution.id,
        "status": execution.status,
        "total_items": total,
        "processed_items": processed_count,
        "remaining_items": remaining_items,
        "success_count": execution.success_count,
        "failure_count": execution.failure_count,
        "percentage": percentage,
        "source_filename": execution.source_filename,
        "requested_by_email": execution.requested_by_email,
        "can_pause": execution.status in {BATCH_STATUS_PENDING, BATCH_STATUS_PROCESSING},
        "can_resume": execution.status == BATCH_STATUS_PAUSED,
        "can_cancel": execution.status in {BATCH_STATUS_PENDING, BATCH_STATUS_PROCESSING, BATCH_STATUS_PAUSED},
    }


@router.post("/executions/{execution_id}/pause", summary="Pausar processamento do lote")
def pause_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(BatchExecution).filter(BatchExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada")
    if execution.status not in {BATCH_STATUS_PENDING, BATCH_STATUS_PROCESSING}:
        raise HTTPException(status_code=409, detail="Somente lotes pendentes ou em processamento podem ser pausados.")

    execution.status = BATCH_STATUS_PAUSED
    execution.worker_id = None
    execution.heartbeat_at = None
    execution.lease_expires_at = None
    db.commit()
    return {"message": "Lote pausado com sucesso.", "status": execution.status}


@router.post("/executions/{execution_id}/resume", summary="Retomar processamento do lote")
def resume_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(BatchExecution).filter(BatchExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada")
    if execution.status != BATCH_STATUS_PAUSED:
        raise HTTPException(status_code=409, detail="Somente lotes pausados podem ser retomados.")

    execution.status = BATCH_STATUS_PENDING
    execution.end_time = None
    execution.worker_id = None
    execution.heartbeat_at = None
    execution.lease_expires_at = None
    db.commit()
    return {"message": "Lote retornou para a fila e sera retomado pelo worker.", "status": execution.status}


@router.post("/executions/{execution_id}/cancel", summary="Cancelar processamento do lote")
def cancel_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(BatchExecution).filter(BatchExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada")
    if execution.status in {BATCH_STATUS_COMPLETED, BATCH_STATUS_COMPLETED_WITH_ERRORS, BATCH_STATUS_CANCELLED}:
        raise HTTPException(status_code=409, detail="Este lote ja foi finalizado.")

    execution.status = BATCH_STATUS_CANCELLED
    execution.worker_id = None
    execution.heartbeat_at = None
    execution.lease_expires_at = None
    if execution.end_time is None:
        execution.end_time = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Lote cancelado com sucesso.", "status": execution.status}


@router.get("/executions/{execution_id}/error-report", summary="Baixar relatorio CSV de erros do lote")
def download_error_report(
    execution_id: int,
    db: Session = Depends(get_db),
):
    execution = (
        db.query(BatchExecution)
        .options(joinedload(BatchExecution.items))
        .filter(BatchExecution.id == execution_id)
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada")

    failed_items = [item for item in execution.items if item.status == "FALHA"]
    if not failed_items:
        raise HTTPException(status_code=404, detail="Esta execucao nao possui itens com falha.")

    csv_content = _build_error_report_csv(failed_items)
    return StreamingResponse(
        iter([csv_content.encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="lote_{execution_id}_erros.csv"'},
    )


@router.get("/executions/{execution_id}", summary="Obter detalhes completos da execucao")
async def get_execution_details(
    execution_id: int,
    db: Session = Depends(get_db),
):
    execution = (
        db.query(BatchExecution)
        .options(joinedload(BatchExecution.items))
        .filter(BatchExecution.id == execution_id)
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada")
    return execution


@router.post("/executions/{execution_id}/retry", summary="Reprocessar itens falhos")
async def retry_execution(
    execution_id: int,
    retry_data: Optional[RetryRequest] = Body(None),
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
):
    target_ids = retry_data.item_ids if retry_data else None
    await service.retry_failed_items(
        original_execution_id=execution_id,
        target_item_ids=target_ids,
    )
    return {"message": "Itens elegiveis reenfileirados para reprocessamento."}
