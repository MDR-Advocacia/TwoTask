"""
Endpoints para gerenciar agendamentos automáticos.

GET    /api/v1/automations              → Listar agendamentos
POST   /api/v1/automations              → Criar agendamento
GET    /api/v1/automations/{id}         → Detalhe do agendamento
PATCH  /api/v1/automations/{id}         → Atualizar agendamento
DELETE /api/v1/automations/{id}         → Deletar agendamento
POST   /api/v1/automations/{id}/run     → Executar agora
GET    /api/v1/automations/{id}/runs    → Histórico de execuções
"""

import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apscheduler.schedulers.background import BackgroundScheduler

from app.core import auth
from app.core.dependencies import get_db
from app.core.scheduler import get_scheduler
from app.models.legal_one import LegalOneUser
from app.models.scheduled_automation import ScheduledAutomationRun
from app.services.scheduled_automation_service import ScheduledAutomationService

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Schemas ────────────────────────────────────────────────────────────────

class AutomationCreateRequest(BaseModel):
    name: str
    office_ids: List[int]
    steps: List[str]  # ["pull_publications", "classify"]
    cron_expression: Optional[str] = None  # "0 7 * * *"
    interval_minutes: Optional[int] = None  # 360
    # Janela de busca (opcional — se omitido usa defaults globais)
    initial_lookback_days: Optional[int] = None
    overlap_hours: Optional[int] = None


class AutomationUpdateRequest(BaseModel):
    name: Optional[str] = None
    office_ids: Optional[List[int]] = None
    steps: Optional[List[str]] = None
    cron_expression: Optional[str] = None
    interval_minutes: Optional[int] = None
    is_enabled: Optional[bool] = None
    initial_lookback_days: Optional[int] = None
    overlap_hours: Optional[int] = None


class AutomationResponseSchema(BaseModel):
    id: int
    name: str
    office_ids: List[int]
    steps: List[str]
    cron_expression: Optional[str]
    interval_minutes: Optional[int]
    is_enabled: bool
    last_run_at: Optional[str]
    last_status: Optional[str]
    next_run_at: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class AutomationRunResponseSchema(BaseModel):
    id: int
    automation_id: int
    started_at: str
    finished_at: Optional[str]
    status: str
    error_message: Optional[str]
    steps_executed: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("", tags=["Automations"])
async def list_automations(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.require_permission("schedule_batch")),
):
    """List all scheduled automations (requires schedule_batch permission)."""
    service = ScheduledAutomationService(db=db)
    automations = service.list_automations()

    # Para cada automação, pega a run mais recente (status + timestamps) para
    # o frontend poder mostrar indicador "em execução".
    latest_runs: dict[int, ScheduledAutomationRun] = {}
    if automations:
        ids = [a.id for a in automations]
        # Subquery: maior id de run por automation_id
        from sqlalchemy import func as _f
        subq = (
            db.query(
                ScheduledAutomationRun.automation_id.label("aid"),
                _f.max(ScheduledAutomationRun.id).label("rid"),
            )
            .filter(ScheduledAutomationRun.automation_id.in_(ids))
            .group_by(ScheduledAutomationRun.automation_id)
            .subquery()
        )
        rows = (
            db.query(ScheduledAutomationRun)
            .join(subq, ScheduledAutomationRun.id == subq.c.rid)
            .all()
        )
        for r in rows:
            latest_runs[r.automation_id] = r

    # Calcula next_run_at dinamicamente a partir do cron/interval (o APScheduler
    # mantém isso internamente, mas não persiste na tabela).
    from datetime import datetime, timedelta, timezone as _tz
    def _compute_next(a_) -> Optional[str]:
        if not a_.is_enabled:
            return None
        now = datetime.now(_tz.utc)
        try:
            if a_.cron_expression:
                from apscheduler.triggers.cron import CronTrigger
                try:
                    from zoneinfo import ZoneInfo
                    br_tz = ZoneInfo("America/Sao_Paulo")
                except Exception:
                    br_tz = _tz.utc
                trig = CronTrigger.from_crontab(a_.cron_expression, timezone=br_tz)
                nxt = trig.get_next_fire_time(None, now)
                return nxt.isoformat() if nxt else None
            if a_.interval_minutes:
                base = a_.last_run_at or a_.created_at or now
                nxt = base + timedelta(minutes=a_.interval_minutes)
                if nxt < now:
                    nxt = now + timedelta(minutes=a_.interval_minutes)
                return nxt.isoformat()
        except Exception:
            return None
        return None

    result = []
    for a in automations:
        lr = latest_runs.get(a.id)
        computed_next = _compute_next(a)
        result.append({
            "id": a.id,
            "name": a.name,
            "office_ids": a.office_ids,
            "steps": a.steps,
            "cron_expression": a.cron_expression,
            "interval_minutes": a.interval_minutes,
            "is_enabled": a.is_enabled,
            "initial_lookback_days": a.initial_lookback_days,
            "overlap_hours": a.overlap_hours,
            "last_run_at": a.last_run_at.isoformat() if a.last_run_at else None,
            "last_status": a.last_status,
            "next_run_at": computed_next or (a.next_run_at.isoformat() if a.next_run_at else None),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "latest_run_status": lr.status if lr else None,
            "latest_run_started_at": lr.started_at.isoformat() if lr and lr.started_at else None,
            "latest_run_finished_at": lr.finished_at.isoformat() if lr and lr.finished_at else None,
            "latest_run_progress_phase": lr.progress_phase if lr else None,
            "latest_run_progress_current": lr.progress_current if lr else None,
            "latest_run_progress_total": lr.progress_total if lr else None,
            "latest_run_progress_message": lr.progress_message if lr else None,
            "latest_run_progress_updated_at": lr.progress_updated_at.isoformat() if lr and lr.progress_updated_at else None,
        })
    return result


@router.post("", status_code=201, tags=["Automations"])
async def create_automation(
    payload: AutomationCreateRequest,
    db: Session = Depends(get_db),
    scheduler: BackgroundScheduler = Depends(get_scheduler),
    current_user: LegalOneUser = Depends(auth.require_permission("schedule_batch")),
):
    """Create a new scheduled automation."""
    if not payload.cron_expression and not payload.interval_minutes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either cron_expression or interval_minutes must be provided"
        )

    service = ScheduledAutomationService(db=db, scheduler=scheduler)
    automation = service.create_automation(
        name=payload.name,
        office_ids=payload.office_ids,
        steps=payload.steps,
        cron_expression=payload.cron_expression,
        interval_minutes=payload.interval_minutes,
        created_by=current_user.id,
        initial_lookback_days=payload.initial_lookback_days,
        overlap_hours=payload.overlap_hours,
    )

    return {
        "id": automation.id,
        "name": automation.name,
        "office_ids": automation.office_ids,
        "steps": automation.steps,
        "cron_expression": automation.cron_expression,
        "interval_minutes": automation.interval_minutes,
        "is_enabled": automation.is_enabled,
        "initial_lookback_days": automation.initial_lookback_days,
        "overlap_hours": automation.overlap_hours,
        "created_at": automation.created_at.isoformat(),
    }


@router.get("/{automation_id}", tags=["Automations"])
async def get_automation(
    automation_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.require_permission("schedule_batch")),
):
    """Get a scheduled automation by ID."""
    service = ScheduledAutomationService(db=db)
    automation = service.get_automation(automation_id)

    if not automation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automation not found")

    return {
        "id": automation.id,
        "name": automation.name,
        "office_ids": automation.office_ids,
        "steps": automation.steps,
        "cron_expression": automation.cron_expression,
        "interval_minutes": automation.interval_minutes,
        "is_enabled": automation.is_enabled,
        "initial_lookback_days": automation.initial_lookback_days,
        "overlap_hours": automation.overlap_hours,
        "last_run_at": automation.last_run_at.isoformat() if automation.last_run_at else None,
        "last_status": automation.last_status,
        "last_error": automation.last_error,
        "next_run_at": automation.next_run_at.isoformat() if automation.next_run_at else None,
        "created_at": automation.created_at.isoformat(),
    }


@router.patch("/{automation_id}", tags=["Automations"])
async def update_automation(
    automation_id: int,
    payload: AutomationUpdateRequest,
    db: Session = Depends(get_db),
    scheduler: BackgroundScheduler = Depends(get_scheduler),
    current_user: LegalOneUser = Depends(auth.require_permission("schedule_batch")),
):
    """Update a scheduled automation."""
    service = ScheduledAutomationService(db=db, scheduler=scheduler)

    try:
        automation = service.update_automation(
            automation_id,
            name=payload.name,
            office_ids=payload.office_ids,
            steps=payload.steps,
            cron_expression=payload.cron_expression,
            interval_minutes=payload.interval_minutes,
            is_enabled=payload.is_enabled,
            initial_lookback_days=payload.initial_lookback_days,
            overlap_hours=payload.overlap_hours,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return {
        "id": automation.id,
        "name": automation.name,
        "office_ids": automation.office_ids,
        "steps": automation.steps,
        "cron_expression": automation.cron_expression,
        "interval_minutes": automation.interval_minutes,
        "is_enabled": automation.is_enabled,
        "initial_lookback_days": automation.initial_lookback_days,
        "overlap_hours": automation.overlap_hours,
        "last_run_at": automation.last_run_at.isoformat() if automation.last_run_at else None,
        "last_status": automation.last_status,
        "updated_at": automation.updated_at.isoformat() if automation.updated_at else None,
    }


@router.delete("/{automation_id}", status_code=204, tags=["Automations"])
async def delete_automation(
    automation_id: int,
    db: Session = Depends(get_db),
    scheduler: BackgroundScheduler = Depends(get_scheduler),
    current_user: LegalOneUser = Depends(auth.require_permission("schedule_batch")),
):
    """Delete a scheduled automation."""
    service = ScheduledAutomationService(db=db, scheduler=scheduler)

    try:
        service.delete_automation(automation_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return None


@router.post("/{automation_id}/run", status_code=202, tags=["Automations"])
async def run_automation_now(
    automation_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.require_permission("schedule_batch")),
):
    """Execute a scheduled automation immediately (in a background task)."""
    service = ScheduledAutomationService(db=db)
    automation = service.get_automation(automation_id)

    if not automation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automation not found")

    # Dispatch execution in background. The service opens its own DB session
    # internally via _execute_automation, so we don't pass `db` here.
    def _run(aid: int) -> None:
        try:
            # Use a fresh service instance with a fresh session to avoid
            # sharing the request-scoped session across threads.
            from app.db.session import SessionLocal
            local_db = SessionLocal()
            try:
                ScheduledAutomationService(db=local_db)._execute_automation(aid)
            finally:
                local_db.close()
        except Exception:
            logger.exception("Error executing automation %d on demand", aid)

    background_tasks.add_task(_run, automation_id)
    logger.info("Automation %d queued for on-demand execution", automation_id)

    return {"message": f"Automation {automation_id} scheduled to run immediately."}


@router.get("/{automation_id}/runs", tags=["Automations"])
async def get_automation_runs(
    automation_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.require_permission("schedule_batch")),
):
    """Get execution history for a scheduled automation."""
    service = ScheduledAutomationService(db=db)

    # Verify automation exists
    automation = service.get_automation(automation_id)
    if not automation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automation not found")

    runs = service.get_runs(automation_id, limit=limit)
    return [
        {
            "id": r.id,
            "automation_id": r.automation_id,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status,
            "error_message": r.error_message,
            "steps_executed": r.steps_executed,
        }
        for r in runs
    ]
