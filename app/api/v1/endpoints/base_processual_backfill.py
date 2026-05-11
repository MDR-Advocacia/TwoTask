"""Endpoints de backfill historico — uploads datados de timestamps passados.

Caso de uso: o operador tem N planilhas historicas (Primeira Tranche +
lotes PLANILHA_MIGRACAO_COMPLETA) e quer popular a timeline do dashboard
com os picos diarios de entrada que aconteceram nos ultimos meses.

2 modos:
- mode=snapshot: pipeline normal de upload (cria/atualiza processos +
  detecta SAIDAS), mas com `uploaded_at` forcado pra timestamp historica.
  Usar pra Primeira Tranche (e opcionalmente pra Listagem final).
- mode=lote_historico: registra SO' a contagem do lote (1 row em
  base_processual_upload com status=LOTE_HISTORICO + summary_novos = N).
  Usar pros PLANILHA_MIGRACAO_COMPLETA que tem schema diferente e so' nos
  interessa a contagem temporal pro dashboard. Trade-off: perde
  granularidade por processo.

Admin-only via require_admin.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.v1.endpoints.base_processual import (
    MAX_XLSX_BYTES,
    _ensure_xlsx_file,
    _result_to_schema,
    require_admin,
)
from app.api.v1.schemas import BaseProcessualUploadResult
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.services.base_processual.storage import save_xlsx
from app.services.base_processual.upload_processor import (
    process_upload,
    register_lote_historico,
)
from app.services.base_processual.xlsx_reader_migracao import (
    MigracaoSchemaError,
    count_processos_no_lote,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/base-processual", tags=["Base Processual"])


@router.post(
    "/uploads/backfill",
    response_model=BaseProcessualUploadResult,
)
async def backfill_upload(
    file: UploadFile = File(...),
    uploaded_at: str = Form(
        ...,
        description="Timestamp ISO 8601 da planilha (ex.: '2026-03-25T17:20:00'). Sera' usado em uploaded_at, processed_at, committed_at + timestamps de todos os snapshots/eventos/processos novos derivados desse upload.",
    ),
    mode: str = Form(
        ...,
        description=(
            "'snapshot' (pipeline normal, detecta SAIDAS) OU 'lote_historico' "
            "(so' conta linhas, nao cria processos individuais — pra "
            "PLANILHA_MIGRACAO_COMPLETA)."
        ),
    ),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Processa um upload historico com timestamp forcada.

    Erros:
    - 400: uploaded_at invalido, mode invalido, ou arquivo invalido
    - 413: arquivo > 30 MB
    """
    # Parse timestamp
    try:
        ts = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"uploaded_at invalido: {uploaded_at!r}. Esperado ISO 8601.",
        ) from exc
    # Remove tzinfo pra alinhar com colunas timestamp without timezone
    if ts.tzinfo is not None:
        from datetime import timezone

        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)

    mode_norm = (mode or "").strip().lower()
    if mode_norm not in ("snapshot", "lote_historico"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"mode invalido: {mode!r}. Use 'snapshot' ou 'lote_historico'.",
        )

    content = await file.read()
    _ensure_xlsx_file(file, content)
    try:
        storage_path, _sha = save_xlsx(content)
    except OSError as exc:
        logger.exception("Falha ao gravar XLSX em disco (backfill)")
        raise HTTPException(
            status_code=500, detail=f"Falha ao gravar arquivo: {exc}"
        ) from exc

    if mode_norm == "snapshot":
        result = process_upload(
            db=db,
            filename=file.filename or "backfill.xlsx",
            content=content,
            uploaded_by_user_id=user.id,
            dry_run=False,
            storage_path=storage_path,
            force_uploaded_at=ts,
        )
        return _result_to_schema(result)

    # mode == lote_historico
    try:
        total_rows = count_processos_no_lote(content)
    except MigracaoSchemaError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    result = register_lote_historico(
        db=db,
        filename=file.filename or "lote-historico.xlsx",
        content=content,
        uploaded_by_user_id=user.id,
        storage_path=storage_path,
        uploaded_at=ts,
        total_rows=total_rows,
    )
    return _result_to_schema(result)
