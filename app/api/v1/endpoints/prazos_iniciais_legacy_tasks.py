from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from app.core import auth as auth_security
from app.models.legal_one import LegalOneUser
from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_CANCELLED_STATUS_ID,
    DEFAULT_CANCELLED_STATUS_TEXT,
    DEFAULT_LEGACY_TASK_CANDIDATE_STATUS_IDS,
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
    LegacyTaskCancellationService,
)

router = APIRouter(prefix="/prazos-iniciais", tags=["Prazos Iniciais"])


class LegacyTaskCancellationRequest(BaseModel):
    cnj_number: Optional[str] = None
    lawsuit_id: Optional[int] = Field(default=None, ge=1)
    task_id: Optional[int] = Field(default=None, ge=1)
    task_type_external_id: int = Field(
        default=DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        ge=1,
    )
    task_subtype_external_id: int = Field(
        default=DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        ge=1,
    )
    candidate_status_ids: list[int] = Field(
        default_factory=lambda: list(DEFAULT_LEGACY_TASK_CANDIDATE_STATUS_IDS)
    )
    target_status_id: int = Field(default=DEFAULT_CANCELLED_STATUS_ID, ge=0)
    target_status_text: str = Field(default=DEFAULT_CANCELLED_STATUS_TEXT, min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def validate_identifiers(self):
        if not any([self.cnj_number, self.lawsuit_id, self.task_id]):
            raise ValueError(
                "Informe ao menos um identificador: cnj_number, lawsuit_id ou task_id."
            )
        return self


class LegacyTaskCancellationResponse(BaseModel):
    success: bool
    reason: str
    cnj_number: Optional[str] = None
    lawsuit_id: Optional[int] = None
    task_id: Optional[int] = None
    candidate_count: Optional[int] = None
    selected_task: Optional[dict[str, Any]] = None
    current_status_id: Optional[int] = None
    target_status_id: int
    target_status_text: str
    runner_state: Optional[str] = None
    runner_item_status: Optional[str] = None
    runner_response: Optional[dict[str, Any]] = None
    runner_error: Optional[str] = None
    process_exit_code: Optional[int] = None
    status_file_path: Optional[str] = None
    log_file_path: Optional[str] = None
    error_log_file_path: Optional[str] = None
    artifacts_dir: Optional[str] = None
    edit_url: Optional[str] = None
    details_url: Optional[str] = None


@router.post(
    "/legacy-task/cancel",
    response_model=LegacyTaskCancellationResponse,
    summary="Cancela a task legado de Agendar Prazos no Legal One.",
)
def cancel_legacy_agendar_prazos_task(
    body: LegacyTaskCancellationRequest,
    _: LegalOneUser = Depends(auth_security.require_permission("prazos_iniciais")),
):
    try:
        service = LegacyTaskCancellationService()
        result = service.cancel_task(
            cnj_number=body.cnj_number,
            lawsuit_id=body.lawsuit_id,
            task_id=body.task_id,
            task_type_external_id=body.task_type_external_id,
            task_subtype_external_id=body.task_subtype_external_id,
            candidate_status_ids=body.candidate_status_ids,
            target_status_id=body.target_status_id,
            target_status_text=body.target_status_text,
            max_attempts=body.max_attempts,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao cancelar a task legado: {exc}",
        ) from exc

    return LegacyTaskCancellationResponse(**result)
