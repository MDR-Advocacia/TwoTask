"""
Feedback livre dos usuarios pra equipe (botao flutuante).

Rotas operador (qualquer JWT):
- POST /feedback — envia feedback novo. Server captura page_url e
  user_agent do payload (frontend pega de window.location e navigator).

Rotas admin (role='admin'):
- GET /admin/feedback — lista paginada (limit+offset, total+items),
  filtros por status e category.
- GET /admin/feedback/stats — contadores por status/category pra UI.
- PATCH /admin/feedback/{id} — atualiza status e/ou admin_note.

Nao tem DELETE: feedback eh historico. Pra apagar de vez, deletar o
LegalOneUser dispara cascata via FK.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.models.user_feedback import (
    FEEDBACK_CATEGORIES_VALIDAS,
    FEEDBACK_STATUS_NEW,
    FEEDBACK_STATUSES_VALIDOS,
    UserFeedback,
)

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────

class FeedbackCreatePayload(BaseModel):
    category: str = Field(..., min_length=1, max_length=32)
    message: str = Field(..., min_length=1, max_length=5000)
    page_url: Optional[str] = Field(default=None, max_length=500)
    user_agent: Optional[str] = Field(default=None, max_length=500)


class FeedbackUpdatePayload(BaseModel):
    status: Optional[str] = Field(default=None, max_length=16)
    admin_note: Optional[str] = Field(default=None, max_length=5000)


class FeedbackOut(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str]
    user_email: Optional[str]
    category: str
    message: str
    page_url: Optional[str]
    user_agent: Optional[str]
    status: str
    admin_note: Optional[str]
    reviewed_by_user_id: Optional[int]
    reviewed_by_name: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class FeedbackListResponse(BaseModel):
    total: int
    items: list[FeedbackOut]


class FeedbackStats(BaseModel):
    total: int
    novo: int
    lido: int
    arquivado: int
    by_category: dict[str, int]


def _ensure_admin(user: LegalOneUser) -> None:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admin pode visualizar feedbacks.",
        )


def _serialize(db: Session, fb: UserFeedback) -> FeedbackOut:
    """Resolve nomes dos users (sender + reviewer) pra UI mostrar
    sem precisar de N+1 chamadas no front."""
    sender = db.get(LegalOneUser, fb.user_id) if fb.user_id else None
    reviewer = (
        db.get(LegalOneUser, fb.reviewed_by_user_id)
        if fb.reviewed_by_user_id else None
    )
    return FeedbackOut(
        id=fb.id,
        user_id=fb.user_id,
        user_name=sender.name if sender else None,
        user_email=sender.email if sender else None,
        category=fb.category,
        message=fb.message,
        page_url=fb.page_url,
        user_agent=fb.user_agent,
        status=fb.status,
        admin_note=fb.admin_note,
        reviewed_by_user_id=fb.reviewed_by_user_id,
        reviewed_by_name=reviewer.name if reviewer else None,
        reviewed_at=fb.reviewed_at,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Rotas operador (envio)
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/feedback",
    summary="Envia feedback do usuario corrente",
    status_code=status.HTTP_201_CREATED,
)
def create_feedback(
    payload: FeedbackCreatePayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    if payload.category not in FEEDBACK_CATEGORIES_VALIDAS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"category invalida: {payload.category}. Use uma de: "
                f"{', '.join(sorted(FEEDBACK_CATEGORIES_VALIDAS))}."
            ),
        )

    fb = UserFeedback(
        user_id=current_user.id,
        category=payload.category,
        message=payload.message.strip(),
        page_url=(payload.page_url or None),
        user_agent=(payload.user_agent or None),
        status=FEEDBACK_STATUS_NEW,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"ok": True, "id": fb.id}


# ──────────────────────────────────────────────────────────────────────
# Rotas admin (listagem + atualizacao)
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/admin/feedback",
    summary="Lista feedbacks (admin) com paginacao + filtros",
    response_model=FeedbackListResponse,
)
def list_feedback(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    category: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    _ensure_admin(current_user)

    q = db.query(UserFeedback)
    if status_filter:
        if status_filter not in FEEDBACK_STATUSES_VALIDOS:
            raise HTTPException(
                status_code=422,
                detail=f"status invalido: {status_filter}",
            )
        q = q.filter(UserFeedback.status == status_filter)
    if category:
        q = q.filter(UserFeedback.category == category)

    total = q.count()
    rows = (
        q.order_by(UserFeedback.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return FeedbackListResponse(
        total=total,
        items=[_serialize(db, r) for r in rows],
    )


@router.get(
    "/admin/feedback/stats",
    summary="Contadores agregados de feedback (admin)",
    response_model=FeedbackStats,
)
def feedback_stats(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    _ensure_admin(current_user)

    total = db.query(UserFeedback).count()
    by_status_rows = (
        db.query(UserFeedback.status, func.count(UserFeedback.id))
        .group_by(UserFeedback.status)
        .all()
    )
    by_status = {s: c for s, c in by_status_rows}

    by_cat_rows = (
        db.query(UserFeedback.category, func.count(UserFeedback.id))
        .group_by(UserFeedback.category)
        .all()
    )
    by_category = {c: n for c, n in by_cat_rows}

    return FeedbackStats(
        total=total,
        novo=by_status.get("novo", 0),
        lido=by_status.get("lido", 0),
        arquivado=by_status.get("arquivado", 0),
        by_category=by_category,
    )


@router.patch(
    "/admin/feedback/{feedback_id}",
    summary="Atualiza status e/ou nota interna de um feedback (admin)",
)
def update_feedback(
    payload: FeedbackUpdatePayload,
    feedback_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    _ensure_admin(current_user)
    fb = db.get(UserFeedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback nao encontrado.")

    changed = False
    if payload.status is not None:
        if payload.status not in FEEDBACK_STATUSES_VALIDOS:
            raise HTTPException(
                status_code=422,
                detail=f"status invalido: {payload.status}",
            )
        if fb.status != payload.status:
            fb.status = payload.status
            # Carimba quem revisou na 1a vez que sai de "novo".
            if fb.reviewed_at is None:
                fb.reviewed_at = datetime.now(timezone.utc)
                fb.reviewed_by_user_id = current_user.id
            changed = True
    if payload.admin_note is not None:
        fb.admin_note = payload.admin_note.strip() or None
        if fb.reviewed_at is None:
            fb.reviewed_at = datetime.now(timezone.utc)
            fb.reviewed_by_user_id = current_user.id
        changed = True

    if changed:
        db.commit()
        db.refresh(fb)
    return _serialize(db, fb).model_dump()
