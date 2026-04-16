"""
Endpoints do tratamento incidental de publicacoes via Legal One web.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import auth
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.services.publication_treatment_service import PublicationTreatmentService

router = APIRouter(prefix="/treatment")


def _parse_office_ids(raw: Optional[str]) -> Optional[list[int]]:
    if not raw:
        return None
    office_ids: list[int] = []
    for chunk in raw.split(","):
        normalized = chunk.strip()
        if not normalized:
            continue
        office_ids.append(int(normalized))
    return office_ids or None


def _get_service(db: Session = Depends(get_db)) -> PublicationTreatmentService:
    return PublicationTreatmentService(db=db)


class StartRunRequest(BaseModel):
    office_ids: Optional[list[int]] = None


class RunControlRequest(BaseModel):
    action: str


@router.get("/summary")
def get_treatment_summary(
    office_ids: Optional[str] = Query(default=None),
    service: PublicationTreatmentService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    return service.get_summary(_parse_office_ids(office_ids))


@router.get("/items")
def get_treatment_items(
    office_ids: Optional[str] = Query(default=None),
    queue_status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: PublicationTreatmentService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    return service.list_items(
        office_ids=_parse_office_ids(office_ids),
        queue_status=queue_status,
        limit=limit,
    )


@router.get("/runs")
def get_treatment_runs(
    limit: int = Query(default=20, ge=1, le=100),
    service: PublicationTreatmentService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    return service.list_runs(limit=limit)


@router.get("/monitor")
def get_treatment_monitor(
    office_ids: Optional[str] = Query(default=None),
    service: PublicationTreatmentService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    return service.get_monitor(office_ids=_parse_office_ids(office_ids))


@router.post("/runs/start")
def start_treatment_run(
    payload: StartRunRequest,
    service: PublicationTreatmentService = Depends(_get_service),
    current_user: LegalOneUser = Depends(auth.require_permission("publications")),
):
    try:
        return service.start_run(
            office_ids=payload.office_ids,
            triggered_by_email=current_user.email,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/control")
def control_treatment_run(
    run_id: int,
    payload: RunControlRequest,
    service: PublicationTreatmentService = Depends(_get_service),
    _: LegalOneUser = Depends(auth.require_permission("publications")),
):
    normalized_action = (payload.action or "").strip().lower()
    if normalized_action not in {"pause", "resume"}:
        raise HTTPException(status_code=400, detail="Acao invalida. Use pause ou resume.")

    try:
        return service.set_run_control(run_id, normalized_action)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
