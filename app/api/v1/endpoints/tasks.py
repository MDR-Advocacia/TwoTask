# file: app/api/v1/endpoints/tasks.py

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.v1.schemas import TaskTriggerPayload
from app.services.orchestration_service import OrchestrationService, ProcessNotFoundError, MissingResponsibleUserError
from app.core.dependencies import get_orchestration_service # Importaremos a mágica da injeção de dependência

# O APIRouter funciona como um "mini-aplicativo" para agrupar endpoints relacionados.
router = APIRouter()

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