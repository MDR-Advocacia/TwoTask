from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.dependencies import get_db
from app.models.legal_one import LegalOneOffice
from app.services.office_lawsuit_index_service import (
    OfficeLawsuitIndexService,
    FULL_SYNC_TTL,
)

router = APIRouter()

# --- Pydantic Schema for Office Data ---
class OfficeResponse(BaseModel):
    id: int
    name: str
    path: str
    external_id: int

    class Config:
        orm_mode = True

@router.get("/offices", response_model=List[OfficeResponse], summary="Listar todos os escritórios ativos", tags=["Offices"])
def get_all_offices(db: Session = Depends(get_db)):
    """
    Retorna uma lista de todos os escritórios (Offices) que estão marcados como ativos no sistema.
    """
    offices = db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).order_by(LegalOneOffice.path).all()
    return offices


# ─── Índice de processos por escritório ─────────────────

class LawsuitIndexStatus(BaseModel):
    office_id: int
    total_ids: int
    in_progress: bool
    progress_pct: int
    last_full_sync_at: Optional[str]
    last_incremental_at: Optional[str]
    last_sync_status: Optional[str]
    last_sync_error: Optional[str]
    supports_incremental: bool
    is_fresh: bool


def _serialize_status(svc: OfficeLawsuitIndexService, office_id: int) -> LawsuitIndexStatus:
    state = svc.get_sync_state(office_id)
    if state is None:
        return LawsuitIndexStatus(
            office_id=office_id,
            total_ids=0,
            in_progress=False,
            progress_pct=0,
            last_full_sync_at=None,
            last_incremental_at=None,
            last_sync_status=None,
            last_sync_error=None,
            supports_incremental=True,
            is_fresh=False,
        )
    return LawsuitIndexStatus(
        office_id=office_id,
        total_ids=state.total_ids or 0,
        in_progress=bool(state.in_progress),
        progress_pct=state.progress_pct or 0,
        last_full_sync_at=state.last_full_sync_at.isoformat() if state.last_full_sync_at else None,
        last_incremental_at=state.last_incremental_at.isoformat() if state.last_incremental_at else None,
        last_sync_status=state.last_sync_status,
        last_sync_error=state.last_sync_error,
        supports_incremental=bool(state.supports_incremental),
        is_fresh=svc.is_fresh(office_id),
    )


@router.get(
    "/offices/{office_id}/lawsuit-index",
    response_model=LawsuitIndexStatus,
    tags=["Offices"],
)
def get_lawsuit_index_status(office_id: int, db: Session = Depends(get_db)):
    svc = OfficeLawsuitIndexService(db)
    return _serialize_status(svc, office_id)


@router.post(
    "/offices/{office_id}/lawsuit-index/sync",
    response_model=LawsuitIndexStatus,
    tags=["Offices"],
)
def trigger_lawsuit_index_sync(
    office_id: int,
    force_full: bool = False,
    db: Session = Depends(get_db),
):
    """
    Dispara sync do índice de processos do escritório em background.
    Se já estiver rodando, apenas retorna o estado atual.
    """
    svc = OfficeLawsuitIndexService(db)
    svc.ensure_sync(office_id, force_full=force_full)
    return _serialize_status(svc, office_id)