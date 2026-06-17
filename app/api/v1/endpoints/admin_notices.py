"""
Avisos broadcast (banner) emitidos pelo admin pra usuarios online.

Rotas operador (qualquer JWT):
- GET /admin/notices/active — lista avisos ativos pendentes de dismiss
  pro usuario corrente. Polling do frontend (a cada 30s).
- POST /admin/notices/{id}/dismiss — marca como fechado pro usuario
  corrente (idempotente).

Rotas admin (role='admin'):
- GET /admin/notices — lista TODOS os avisos (independente de janela).
- POST /admin/notices — cria novo.
- PATCH /admin/notices/{id} — edita.
- DELETE /admin/notices/{id} — apaga (cascata limpa dismissals).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import auth as auth_security
from app.core.dependencies import get_db
from app.models.admin_notice import (
    NOTICE_SEVERITIES_VALIDAS,
    NOTICE_SEVERITY_INFO,
    AdminNotice,
    AdminNoticeDismissal,
    AdminNoticeView,
)
from app.models.legal_one import LegalOneUser

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────

class NoticeCreatePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1)
    severity: str = Field(default=NOTICE_SEVERITY_INFO)
    # require_ack=True -> aviso vira pop-up bloqueante (exige clicar "Ciente").
    require_ack: bool = False
    starts_at: datetime
    ends_at: datetime


class NoticeUpdatePayload(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    message: Optional[str] = Field(default=None, min_length=1)
    severity: Optional[str] = None
    require_ack: Optional[bool] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class NoticesSeenPayload(BaseModel):
    """IDs de avisos atualmente renderizados na tela do usuario corrente."""
    ids: List[int] = Field(default_factory=list)


class NoticeAudienceEntry(BaseModel):
    user_id: int
    name: Optional[str]
    email: Optional[str]
    at: datetime


class NoticeAudienceOut(BaseModel):
    notice_id: int
    seen: List[NoticeAudienceEntry]
    acknowledged: List[NoticeAudienceEntry]


class NoticeOut(BaseModel):
    id: int
    title: str
    message: str
    severity: str
    require_ack: bool
    starts_at: datetime
    ends_at: datetime
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    # Status calculado: agendado (starts > now), ativo (now em janela),
    # expirado (ends < now). Util pra ordenacao/badge na UI admin.
    status: str
    seen_count: int
    dismissed_count: int


def _serialize(db: Session, notice: AdminNotice) -> NoticeOut:
    now = datetime.now(timezone.utc)
    if notice.starts_at > now:
        st = "agendado"
    elif notice.ends_at < now:
        st = "expirado"
    else:
        st = "ativo"
    dismissed = (
        db.query(AdminNoticeDismissal)
        .filter(AdminNoticeDismissal.notice_id == notice.id)
        .count()
    )
    seen = (
        db.query(AdminNoticeView)
        .filter(AdminNoticeView.notice_id == notice.id)
        .count()
    )
    return NoticeOut(
        id=notice.id,
        title=notice.title,
        message=notice.message,
        severity=notice.severity,
        require_ack=bool(notice.require_ack),
        starts_at=notice.starts_at,
        ends_at=notice.ends_at,
        created_by_user_id=notice.created_by_user_id,
        created_at=notice.created_at,
        updated_at=notice.updated_at,
        status=st,
        seen_count=seen,
        dismissed_count=dismissed,
    )


def _validate_severity(value: str) -> str:
    if value not in NOTICE_SEVERITIES_VALIDAS:
        raise HTTPException(
            status_code=422,
            detail=f"severity invalida: {value}. Use info/warning/danger.",
        )
    return value


def _ensure_admin(user: LegalOneUser) -> None:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admin pode gerenciar avisos.",
        )


# ──────────────────────────────────────────────────────────────────────
# Rotas operador
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/admin/notices/active",
    summary="Avisos ativos pendentes de dismiss pro usuario corrente",
)
def list_active_notices(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """
    Filtros aplicados no SQL:
      - starts_at <= now() AND ends_at >= now() (janela ativa)
      - id NOT IN (notice_ids ja' dispensados pelo user corrente) —
        garante "uma vez por usuario"

    Ordenado por ends_at ASC pra avisos com vencimento proximo
    aparecerem primeiro. NOT IN sub-select e' mais portavel entre
    versoes do SQLAlchemy do que `not_(exists(query_object))`, que
    quebra dependendo de como o ORM constroi o subquery.
    """
    now = datetime.now(timezone.utc)

    # `select()` (em vez de `subquery()`) evita o SAWarning
    # "Coercing Subquery object into a select() for use in IN()"
    # — IN() em SQLAlchemy 2.x quer um Select, nao um Subquery.
    dismissed_select = (
        select(AdminNoticeDismissal.notice_id)
        .where(AdminNoticeDismissal.user_id == current_user.id)
    )

    rows = (
        db.query(AdminNotice)
        .filter(AdminNotice.starts_at <= now)
        .filter(AdminNotice.ends_at >= now)
        .filter(~AdminNotice.id.in_(dismissed_select))
        .order_by(AdminNotice.ends_at.asc())
        .all()
    )

    return [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "severity": n.severity,
            "require_ack": bool(n.require_ack),
            "starts_at": n.starts_at.isoformat() if n.starts_at else None,
            "ends_at": n.ends_at.isoformat() if n.ends_at else None,
        }
        for n in rows
    ]


@router.post(
    "/admin/notices/seen",
    summary="Registra impressao (aviso renderizado) pro usuario corrente",
)
def mark_notices_seen(
    payload: NoticesSeenPayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """
    Chamado pelo front quando um ou mais avisos sao efetivamente exibidos
    (banner ou pop-up). Upsert idempotente em admin_notice_views: cria a
    linha com first_seen_at na primeira vez, e so atualiza last_seen_at nas
    seguintes. Ignora ids inexistentes silenciosamente (FK cuida).

    Diferente de /dismiss: ver != confirmar. Um aviso visto mas nao
    confirmado fica em views sem entrar em dismissals.
    """
    if not payload.ids:
        return {"ok": True, "recorded": 0}

    # Dedup + so ids de avisos que existem (evita estourar FK em lote).
    wanted = {int(i) for i in payload.ids}
    valid_ids = {
        row[0]
        for row in db.query(AdminNotice.id).filter(AdminNotice.id.in_(wanted)).all()
    }
    if not valid_ids:
        return {"ok": True, "recorded": 0}

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(AdminNoticeView)
        .values([
            {
                "notice_id": nid,
                "user_id": current_user.id,
                "first_seen_at": now,
                "last_seen_at": now,
            }
            for nid in valid_ids
        ])
        .on_conflict_do_update(
            index_elements=["notice_id", "user_id"],
            set_={"last_seen_at": now},
        )
    )
    db.execute(stmt)
    db.commit()
    return {"ok": True, "recorded": len(valid_ids)}


@router.post(
    "/admin/notices/{notice_id}/dismiss",
    summary="Marca aviso como fechado pro usuario corrente (idempotente)",
)
def dismiss_notice(
    notice_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    notice = db.get(AdminNotice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="Aviso nao encontrado.")

    existing = (
        db.query(AdminNoticeDismissal)
        .filter(
            AdminNoticeDismissal.notice_id == notice_id,
            AdminNoticeDismissal.user_id == current_user.id,
        )
        .one_or_none()
    )
    if existing is None:
        db.add(AdminNoticeDismissal(
            notice_id=notice_id,
            user_id=current_user.id,
        ))
        db.commit()
    return {"ok": True, "notice_id": notice_id}


# ──────────────────────────────────────────────────────────────────────
# Rotas admin (CRUD)
# ──────────────────────────────────────────────────────────────────────


@router.get("/admin/notices", summary="Lista todos os avisos (admin)")
def list_all_notices(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    _ensure_admin(current_user)
    rows = (
        db.query(AdminNotice)
        .order_by(AdminNotice.starts_at.desc())
        .all()
    )
    return [_serialize(db, n).model_dump() for n in rows]


@router.get(
    "/admin/notices/{notice_id}/audience",
    summary="Quem viu e quem confirmou um aviso (admin)",
)
def notice_audience(
    notice_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    """
    Detalhe por usuario do aviso: lista de quem o VIU (impressao) e de quem
    o CONFIRMOU/dispensou. Cada item traz nome, email e horario. Usado pelo
    contador clicavel "Visto por N / Confirmado por M" no painel admin.
    """
    _ensure_admin(current_user)
    notice = db.get(AdminNotice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="Aviso nao encontrado.")

    seen_rows = (
        db.query(AdminNoticeView, LegalOneUser)
        .join(LegalOneUser, LegalOneUser.id == AdminNoticeView.user_id)
        .filter(AdminNoticeView.notice_id == notice_id)
        .order_by(AdminNoticeView.first_seen_at.asc())
        .all()
    )
    ack_rows = (
        db.query(AdminNoticeDismissal, LegalOneUser)
        .join(LegalOneUser, LegalOneUser.id == AdminNoticeDismissal.user_id)
        .filter(AdminNoticeDismissal.notice_id == notice_id)
        .order_by(AdminNoticeDismissal.dismissed_at.asc())
        .all()
    )

    return NoticeAudienceOut(
        notice_id=notice_id,
        seen=[
            NoticeAudienceEntry(
                user_id=u.id, name=u.name, email=u.email, at=v.first_seen_at,
            )
            for v, u in seen_rows
        ],
        acknowledged=[
            NoticeAudienceEntry(
                user_id=u.id, name=u.name, email=u.email, at=d.dismissed_at,
            )
            for d, u in ack_rows
        ],
    ).model_dump()


@router.post(
    "/admin/notices",
    summary="Cria um aviso (admin)",
    status_code=status.HTTP_201_CREATED,
)
def create_notice(
    payload: NoticeCreatePayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    _ensure_admin(current_user)
    _validate_severity(payload.severity)
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(
            status_code=422,
            detail="ends_at precisa ser posterior a starts_at.",
        )

    notice = AdminNotice(
        title=payload.title.strip(),
        message=payload.message.strip(),
        severity=payload.severity,
        require_ack=payload.require_ack,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        created_by_user_id=current_user.id,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return _serialize(db, notice).model_dump()


@router.patch(
    "/admin/notices/{notice_id}",
    summary="Edita um aviso (admin)",
)
def update_notice(
    payload: NoticeUpdatePayload,
    notice_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    _ensure_admin(current_user)
    notice = db.get(AdminNotice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="Aviso nao encontrado.")

    if payload.title is not None:
        notice.title = payload.title.strip()
    if payload.message is not None:
        notice.message = payload.message.strip()
    if payload.severity is not None:
        _validate_severity(payload.severity)
        notice.severity = payload.severity
    if payload.require_ack is not None:
        notice.require_ack = payload.require_ack
    if payload.starts_at is not None:
        notice.starts_at = payload.starts_at
    if payload.ends_at is not None:
        notice.ends_at = payload.ends_at
    if notice.ends_at <= notice.starts_at:
        raise HTTPException(
            status_code=422,
            detail="ends_at precisa ser posterior a starts_at.",
        )

    db.commit()
    db.refresh(notice)
    return _serialize(db, notice).model_dump()


@router.delete(
    "/admin/notices/{notice_id}",
    summary="Apaga um aviso (admin) — cascata em dismissals",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_notice(
    notice_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth_security.get_current_user),
):
    _ensure_admin(current_user)
    notice = db.get(AdminNotice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="Aviso nao encontrado.")
    db.delete(notice)
    db.commit()
    return None
