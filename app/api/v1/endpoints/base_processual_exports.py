"""Endpoints de relatorios XLSX (Chunk 5).

POST /exports cria + processa SINCRONO + persiste o XLSX em
$BASE_PROCESSUAL_EXPORTS_DIR (default /data/base-processual/exports/).
GET /exports lista historico paginado. GET /exports/{id}/download serve
o XLSX gerado.

V1 sincrono: pra carteira de ~6k processos cada template fica em <5s.
Se passar de 15s o cliente HTTP pode timeoutar — em v2 mover pra
APScheduler com polling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.v1.endpoints.base_processual import require_admin
from app.api.v1.schemas import (
    BaseProcessualExportCreate,
    BaseProcessualExportListResponse,
    BaseProcessualExportOut,
)
from app.core.dependencies import get_db
from app.models.base_processual import (
    BaseProcessualExport,
    EXPORT_STATUS_FALHOU,
    EXPORT_STATUS_PRONTO,
    EXPORT_STATUS_PROCESSANDO,
    EXPORT_TEMPLATES,
)
from app.models.legal_one import LegalOneUser
from app.services.base_processual.exporter import (
    dispatch_template,
    list_templates,
)
from app.services.base_processual.storage import save_export_xlsx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/base-processual", tags=["Base Processual"])

# Retencao default: 90 dias (configuravel em fase 2 via env).
EXPORT_RETENTION_DAYS = 90


@router.get("/exports/templates", response_model=list[str])
def list_export_templates(
    user: LegalOneUser = Depends(require_admin),
):
    """Lista nomes dos templates disponiveis pra UI montar o seletor."""
    return list_templates()


@router.post("/exports", response_model=BaseProcessualExportOut)
def create_export(
    payload: BaseProcessualExportCreate,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Cria + processa o export sincrono. Devolve linha com status=PRONTO ou FALHOU."""
    template = (payload.template or "").strip()
    if template not in EXPORT_TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Template invalido: {template!r}. "
                f"Validos: {list(EXPORT_TEMPLATES)}"
            ),
        )

    now = datetime.utcnow()
    export = BaseProcessualExport(
        template_name=template,
        params_json=payload.params or {},
        status=EXPORT_STATUS_PROCESSANDO,
        requested_by_user_id=user.id,
        requested_at=now,
        started_at=now,
        expires_at=now + timedelta(days=EXPORT_RETENTION_DAYS),
    )
    db.add(export)
    db.flush()  # pra ter o id

    try:
        xlsx_bytes, total_rows, normalized = dispatch_template(
            template, db, payload.params or {}
        )
        file_path = save_export_xlsx(export.id, xlsx_bytes)
        export.status = EXPORT_STATUS_PRONTO
        export.file_path = file_path
        export.file_bytes = len(xlsx_bytes)
        export.total_rows = total_rows
        export.params_json = normalized
        export.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(export)
        return BaseProcessualExportOut.model_validate(export)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao gerar export #%s (template=%s).", export.id, template)
        db.rollback()
        # Persiste falha numa transacao nova
        export_fail = BaseProcessualExport(
            template_name=template,
            params_json=payload.params or {},
            status=EXPORT_STATUS_FALHOU,
            error_message=f"{type(exc).__name__}: {exc}",
            requested_by_user_id=user.id,
            requested_at=now,
            started_at=now,
            finished_at=datetime.utcnow(),
        )
        db.add(export_fail)
        db.commit()
        db.refresh(export_fail)
        return BaseProcessualExportOut.model_validate(export_fail)


@router.get("/exports", response_model=BaseProcessualExportListResponse)
def list_exports(
    template: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Historico de exports — mais recente primeiro."""
    q = db.query(BaseProcessualExport).order_by(
        BaseProcessualExport.requested_at.desc()
    )
    if template:
        q = q.filter(BaseProcessualExport.template_name == template)
    if status_filter:
        q = q.filter(BaseProcessualExport.status == status_filter)
    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualExportListResponse(
        total=total,
        items=[BaseProcessualExportOut.model_validate(e) for e in items],
    )


@router.get("/exports/{export_id}", response_model=BaseProcessualExportOut)
def get_export(
    export_id: int,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    e = (
        db.query(BaseProcessualExport)
        .filter(BaseProcessualExport.id == export_id)
        .first()
    )
    if e is None:
        raise HTTPException(
            status_code=404, detail=f"Export #{export_id} nao encontrado."
        )
    return BaseProcessualExportOut.model_validate(e)


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: int,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    e = (
        db.query(BaseProcessualExport)
        .filter(BaseProcessualExport.id == export_id)
        .first()
    )
    if e is None:
        raise HTTPException(
            status_code=404, detail=f"Export #{export_id} nao encontrado."
        )
    if e.status != EXPORT_STATUS_PRONTO or not e.file_path:
        raise HTTPException(
            status_code=409,
            detail=f"Export #{export_id} nao esta PRONTO (status={e.status}).",
        )
    filename = f"base-processual-{e.template_name}-{e.id}.xlsx"
    return FileResponse(
        path=e.file_path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        filename=filename,
    )
