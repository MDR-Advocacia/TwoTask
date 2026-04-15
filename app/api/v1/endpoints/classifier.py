"""
Endpoints do motor de classificação de publicações judiciais.

Rotas:
  POST   /upload-preview   → Preview da planilha antes de classificar
  POST   /start            → Inicia classificação de um batch
  GET    /batches           → Lista batches recentes
  GET    /batches/{id}      → Status de um batch específico
  GET    /batches/{id}/results  → Resultados detalhados
  GET    /batches/{id}/export   → Download da planilha classificada
  POST   /batches/{id}/cancel   → Cancela um batch em andamento
"""

from io import BytesIO

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core import auth as auth_security
from app.core.dependencies import get_classification_service
from app.core.uploads import validate_spreadsheet_file_metadata
from app.services.classifier.classification_service import ClassificationService

router = APIRouter()


@router.post("/upload-preview")
async def upload_preview(
    file: UploadFile = File(...),
    service: ClassificationService = Depends(get_classification_service),
):
    """Faz upload da planilha e retorna preview das linhas encontradas."""
    validate_spreadsheet_file_metadata(file)
    content = await file.read()
    try:
        preview = service.build_preview(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Erro ao ler planilha: {exc}")
    return preview


@router.post("/start")
async def start_classification(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    service: ClassificationService = Depends(get_classification_service),
    current_user=Depends(auth_security.get_current_user),
):
    """Cria o batch e inicia a classificação em background."""
    validate_spreadsheet_file_metadata(file)
    content = await file.read()

    try:
        batch = service.create_batch(
            file_content=content,
            filename=file.filename,
            requested_by=current_user.email if hasattr(current_user, "email") else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Erro ao criar batch: {exc}")

    # Processa em background para não bloquear a resposta
    background_tasks.add_task(_run_classification, service, batch.id)

    return {
        "batch_id": batch.id,
        "status": batch.status,
        "total_items": batch.total_items,
        "message": "Classificação iniciada. Acompanhe pelo status.",
    }


async def _run_classification(service: ClassificationService, batch_id: int):
    """Wrapper para rodar a classificação como background task."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        result = await service.process_batch(batch_id)
        logger.info("Batch %s finalizado: %s", batch_id, result)
    except Exception as exc:
        logger.error("Erro fatal no batch %s: %s", batch_id, exc)


@router.get("/batches")
async def list_batches(
    service: ClassificationService = Depends(get_classification_service),
):
    """Lista os batches de classificação mais recentes."""
    return service.list_batches()


@router.get("/batches/{batch_id}")
async def get_batch_status(
    batch_id: int,
    service: ClassificationService = Depends(get_classification_service),
):
    """Retorna o status atual de um batch."""
    try:
        return service.get_batch_status(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/batches/{batch_id}/results")
async def get_batch_results(
    batch_id: int,
    service: ClassificationService = Depends(get_classification_service),
):
    """Retorna resultados detalhados de classificação de cada item."""
    results = service.get_batch_results(batch_id)
    if not results:
        raise HTTPException(status_code=404, detail="Nenhum resultado encontrado.")
    return results


@router.get("/batches/{batch_id}/export")
async def export_batch_results(
    batch_id: int,
    service: ClassificationService = Depends(get_classification_service),
):
    """Exporta os resultados como planilha XLSX para download."""
    try:
        xlsx_bytes = service.export_results_to_xlsx(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=classificacao_batch_{batch_id}.xlsx"
        },
    )


@router.post("/batches/{batch_id}/cancel")
async def cancel_batch(
    batch_id: int,
    service: ClassificationService = Depends(get_classification_service),
):
    """Cancela um batch em andamento."""
    cancelled = service.cancel_batch(batch_id)
    if not cancelled:
        raise HTTPException(
            status_code=400,
            detail="Batch não pode ser cancelado (já finalizado ou não encontrado).",
        )
    return {"batch_id": batch_id, "status": "CANCELADO"}
