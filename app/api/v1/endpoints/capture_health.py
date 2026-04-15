"""
Endpoints de saúde da captura de publicações.

Mostra o estado por escritório (cursor, falhas, dead-letter) e permite
ações manuais como "resetar falhas" quando o operador resolveu o problema.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import auth
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneOffice, LegalOneUser
from app.models.publication_capture import (
    OfficePublicationCursor,
    PublicationFetchAttempt,
    ATTEMPT_STATUS_DEAD_LETTER,
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_SUCCESS,
    CURSOR_STATUS_OK,
    CURSOR_STATUS_DEAD_LETTER,
)

router = APIRouter()


class OfficeHealthSchema(BaseModel):
    office_id: int
    office_name: Optional[str]
    last_successful_date: Optional[datetime]
    last_run_at: Optional[datetime]
    last_status: Optional[str]
    last_error: Optional[str]
    consecutive_failures: int
    next_retry_at: Optional[datetime]
    health: str  # ok, warning, critical, dead_letter, never_ran


class CaptureHealthSummarySchema(BaseModel):
    total_offices: int
    ok: int
    warning: int
    critical: int
    dead_letter: int
    never_ran: int
    offices: List[OfficeHealthSchema]


def _classify_health(
    cursor: Optional[OfficePublicationCursor],
    now: datetime,
) -> str:
    if cursor is None or cursor.last_run_at is None:
        return "never_ran"
    if cursor.last_status == CURSOR_STATUS_DEAD_LETTER:
        return "dead_letter"
    failures = cursor.consecutive_failures or 0
    if failures >= 3:
        return "critical"
    if failures >= 1:
        return "warning"
    # last_run_at > 3h atrás já é sinal amarelo (SLA 6h)
    age = (now - cursor.last_run_at).total_seconds() / 3600
    if age > 3:
        return "warning"
    return "ok"


@router.get("/capture-health", response_model=CaptureHealthSummarySchema, tags=["Admin"])
def get_capture_health(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Status consolidado da captura por escritório."""
    now = datetime.now(timezone.utc)

    # Escritórios que aparecem em algum cursor OU que estão ativos
    offices = {o.external_id: o for o in db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).all()}
    cursors = {c.office_id: c for c in db.query(OfficePublicationCursor).all()}

    # Próximos retries pendentes por office
    pending_retries = (
        db.query(PublicationFetchAttempt)
        .filter(PublicationFetchAttempt.status == ATTEMPT_STATUS_FAILED)
        .filter(PublicationFetchAttempt.next_retry_at != None)  # noqa: E711
        .order_by(PublicationFetchAttempt.id.desc())
        .all()
    )
    next_retry_by_office: dict[int, datetime] = {}
    for a in pending_retries:
        if a.office_id not in next_retry_by_office:
            next_retry_by_office[a.office_id] = a.next_retry_at

    all_office_ids = set(offices.keys()) | set(cursors.keys())

    rows: List[OfficeHealthSchema] = []
    counts = {"ok": 0, "warning": 0, "critical": 0, "dead_letter": 0, "never_ran": 0}

    for office_id in sorted(all_office_ids):
        cursor = cursors.get(office_id)
        office = offices.get(office_id)
        health = _classify_health(cursor, now)
        counts[health] += 1
        rows.append(OfficeHealthSchema(
            office_id=office_id,
            office_name=(office.path or office.name) if office else f"Escritório {office_id}",
            last_successful_date=cursor.last_successful_date if cursor else None,
            last_run_at=cursor.last_run_at if cursor else None,
            last_status=cursor.last_status if cursor else None,
            last_error=cursor.last_error if cursor else None,
            consecutive_failures=cursor.consecutive_failures if cursor else 0,
            next_retry_at=next_retry_by_office.get(office_id),
            health=health,
        ))

    return CaptureHealthSummarySchema(
        total_offices=len(rows),
        ok=counts["ok"],
        warning=counts["warning"],
        critical=counts["critical"],
        dead_letter=counts["dead_letter"],
        never_ran=counts["never_ran"],
        offices=rows,
    )


class ResetOfficeRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/capture-health/{office_id}/reset", tags=["Admin"])
def reset_office_capture(
    office_id: int,
    payload: ResetOfficeRequest,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Zera contador de falhas e dead-letter para o escritório, retomando a captura normal."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    cursor = db.query(OfficePublicationCursor).filter(
        OfficePublicationCursor.office_id == office_id
    ).first()
    if not cursor:
        raise HTTPException(status_code=404, detail="Escritório sem histórico de captura.")

    cursor.consecutive_failures = 0
    cursor.last_status = CURSOR_STATUS_OK
    cursor.last_error = None

    # Limpa attempts em backoff pendente para o office
    db.query(PublicationFetchAttempt).filter(
        PublicationFetchAttempt.office_id == office_id,
        PublicationFetchAttempt.status.in_([ATTEMPT_STATUS_FAILED, ATTEMPT_STATUS_DEAD_LETTER]),
        PublicationFetchAttempt.next_retry_at != None,  # noqa: E711
    ).update({"next_retry_at": None}, synchronize_session=False)

    db.commit()
    db.refresh(cursor)
    return {"office_id": office_id, "message": "Captura resetada. Próxima execução tentará normalmente."}
