import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.core import auth
from app.core.dependencies import get_batch_task_creation_service, get_db
from app.models.legal_one import LegalOneTaskType, LegalOneUser, SavedFilter
from app.models.rules import Squad
from app.models.task_group import TaskParentGroup
from app.services.batch_task_creation_service import BatchTaskCreationService
from app.services.metadata_sync_service import run_metadata_sync_job

router = APIRouter()
me_router = APIRouter()
logger = logging.getLogger(__name__)


class TaskSubTypeSchema(BaseModel):
    id: int
    name: str
    squad_ids: List[int]


class TaskTypeGroupSchema(BaseModel):
    parent_id: int
    parent_name: str
    sub_types: List[TaskSubTypeSchema]


class TaskTypeAssociationPayload(BaseModel):
    squad_ids: List[int]
    task_type_ids: List[int]


class TaskParentGroupUpdatePayload(BaseModel):
    name: str


@router.post("/sync-metadata", status_code=202, summary="Sincronizar metadados do Legal One", tags=["Admin"])
def sync_metadata(
    background_tasks: BackgroundTasks,
):
    logger.info("Endpoint /sync-metadata chamado. Adicionando tarefa em background.")
    background_tasks.add_task(run_metadata_sync_job)
    return {"message": "Processo de sincronizacao de metadados do Legal One iniciado em segundo plano."}


@router.post(
    "/sync-caches",
    status_code=202,
    summary="Pré-carregar caches de escritórios e processos",
    tags=["Admin"],
)
def sync_caches(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Dispara em background o pre-warm dos caches:
    1. Índice de processos por escritório (office_lawsuit_index)
    2. Cache de dados do processo (lawsuit_cache: CNJ, creationDate, officeId)

    Evita que a primeira busca de publicações seja lenta e economiza
    chamadas à API do Legal One.
    """
    from app.models.legal_one import LegalOneOffice

    offices = (
        db.query(LegalOneOffice)
        .filter(LegalOneOffice.is_active == True)  # noqa: E712
        .all()
    )
    office_ids = [o.external_id for o in offices]

    if not office_ids:
        return {"message": "Nenhum escritório ativo encontrado."}

    def _run():
        from app.db.session import SessionLocal
        from app.services.office_lawsuit_index_service import OfficeLawsuitIndexService
        from app.services.legal_one_client import LegalOneApiClient

        bg_db = SessionLocal()
        try:
            client = LegalOneApiClient()
            svc = OfficeLawsuitIndexService(bg_db, client)

            for oid in office_ids:
                logger.info("Pre-warm: sync índice escritório %s", oid)
                try:
                    svc.ensure_sync(oid, force_full=False)
                except Exception as exc:
                    logger.warning("Pre-warm: falha no índice do escritório %s: %s", oid, exc)

            # Pre-warm lawsuit_cache: busca dados (CNJ + creationDate) de todos
            # os processos indexados. O client salva automaticamente no cache.
            from app.models.office_lawsuit_index import OfficeLawsuitIndex

            all_lawsuit_ids = [
                r[0]
                for r in bg_db.query(OfficeLawsuitIndex.lawsuit_id).distinct().all()
            ]
            logger.info("Pre-warm: carregando cache de %s processos...", len(all_lawsuit_ids))

            if all_lawsuit_ids:
                # fetch_lawsuits_by_ids já usa e popula o lawsuit_cache
                BATCH = 500
                for i in range(0, len(all_lawsuit_ids), BATCH):
                    chunk = all_lawsuit_ids[i:i + BATCH]
                    try:
                        client.fetch_lawsuits_by_ids(chunk)
                    except Exception as exc:
                        logger.warning("Pre-warm: falha no batch %s-%s: %s", i, i + len(chunk), exc)

            logger.info("Pre-warm: concluído. %s escritórios, %s processos.", len(office_ids), len(all_lawsuit_ids))
        except Exception as exc:
            logger.exception("Pre-warm: erro geral: %s", exc)
        finally:
            bg_db.close()

    background_tasks.add_task(_run)
    return {
        "message": f"Pre-warm de caches iniciado para {len(office_ids)} escritórios.",
        "offices": len(office_ids),
    }


@router.get(
    "/cache-status",
    summary="Status dos caches de escritórios e processos",
    tags=["Admin"],
)
def get_cache_status(db: Session = Depends(get_db)):
    """
    Retorna status detalhado dos caches:
    - Índice de processos por escritório (office_lawsuit_index)
    - Cache de dados dos processos (lawsuit_cache)
    - Metadados (escritórios, usuários, tipos de tarefa)
    """
    from app.models.legal_one import LegalOneOffice, LegalOneUser, LegalOneTaskType
    from app.models.office_lawsuit_index import OfficeLawsuitIndex, OfficeLawsuitSync
    from app.models.lawsuit_cache import LawsuitCache, LAWSUIT_CACHE_TTL
    from app.services.office_lawsuit_index_service import FULL_SYNC_TTL
    from datetime import datetime, timezone
    from sqlalchemy import func as sa_func

    # ── Metadados ──
    offices_count = db.query(sa_func.count(LegalOneOffice.id)).filter(
        LegalOneOffice.is_active == True  # noqa: E712
    ).scalar() or 0
    users_count = db.query(sa_func.count(LegalOneUser.id)).filter(
        LegalOneUser.is_active == True  # noqa: E712
    ).scalar() or 0
    task_types_count = db.query(sa_func.count(LegalOneTaskType.id)).scalar() or 0

    # ── Índices por escritório ──
    sync_states = db.query(OfficeLawsuitSync).all()
    now = datetime.now(timezone.utc)

    offices_index = []
    any_in_progress = False
    total_indexed = 0

    # Nomes dos escritórios
    office_names: dict[int, str] = {}
    if sync_states:
        oids = [s.office_id for s in sync_states]
        rows = db.query(LegalOneOffice).filter(LegalOneOffice.external_id.in_(oids)).all()
        office_names = {o.external_id: o.name for o in rows}

    for s in sync_states:
        last = s.last_full_sync_at
        is_fresh = False
        if last:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            is_fresh = (now - last) < FULL_SYNC_TTL

        offices_index.append({
            "office_id": s.office_id,
            "office_name": office_names.get(s.office_id, f"ID {s.office_id}"),
            "total_ids": s.total_ids or 0,
            "in_progress": bool(s.in_progress),
            "progress_pct": s.progress_pct or 0,
            "status": s.last_sync_status,
            "error": s.last_sync_error,
            "is_fresh": is_fresh,
            "last_sync": s.finished_at.isoformat() if s.finished_at else None,
        })
        if s.in_progress:
            any_in_progress = True
        total_indexed += (s.total_ids or 0)

    # ── Cache de processos ──
    lawsuit_cache_total = db.query(sa_func.count(LawsuitCache.lawsuit_id)).scalar() or 0
    cutoff = now - LAWSUIT_CACHE_TTL
    lawsuit_cache_fresh = db.query(sa_func.count(LawsuitCache.lawsuit_id)).filter(
        LawsuitCache.fetched_at >= cutoff
    ).scalar() or 0
    lawsuit_cache_stale = lawsuit_cache_total - lawsuit_cache_fresh

    return {
        "metadata": {
            "offices": offices_count,
            "users": users_count,
            "task_types": task_types_count,
        },
        "office_index": {
            "offices": offices_index,
            "total_indexed": total_indexed,
            "any_in_progress": any_in_progress,
        },
        "lawsuit_cache": {
            "total": lawsuit_cache_total,
            "fresh": lawsuit_cache_fresh,
            "stale": lawsuit_cache_stale,
            "ttl_hours": LAWSUIT_CACHE_TTL.total_seconds() / 3600,
        },
    }


@router.get(
    "/task-types",
    summary="Listar tipos de tarefa agrupados",
    tags=["Admin"],
    response_model=List[TaskTypeGroupSchema],
)
def get_task_types_grouped(db: Session = Depends(get_db)):
    task_types = db.query(LegalOneTaskType).options(
        joinedload(LegalOneTaskType.subtypes),
        joinedload(LegalOneTaskType.squads),
    ).order_by(LegalOneTaskType.name).all()
    custom_group_names = {group.id: group.name for group in db.query(TaskParentGroup).all()}

    response_data = []
    for task_type in task_types:
        squad_ids = [squad.id for squad in task_type.squads]
        sub_types_data = [
            TaskSubTypeSchema(
                id=sub_type.id,
                name=sub_type.name,
                squad_ids=squad_ids,
            )
            for sub_type in sorted(task_type.subtypes, key=lambda item: item.name)
        ]

        response_data.append(
            TaskTypeGroupSchema(
                parent_id=task_type.id,
                parent_name=custom_group_names.get(task_type.id, task_type.name),
                sub_types=sub_types_data,
            )
        )

    return response_data


@router.put("/task-parent-groups/{parent_id}", summary="Renomear grupo pai de tarefas", tags=["Admin"])
def update_task_parent_group(
    parent_id: int,
    payload: TaskParentGroupUpdatePayload,
    db: Session = Depends(get_db),
):
    task_type = db.query(LegalOneTaskType).filter(LegalOneTaskType.id == parent_id).first()
    if not task_type:
        raise HTTPException(status_code=404, detail="Grupo de tarefa nao encontrado.")

    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="O nome do grupo nao pode ficar vazio.")

    group = db.query(TaskParentGroup).filter(TaskParentGroup.id == parent_id).first()
    if group is None:
        group = TaskParentGroup(id=parent_id, name=normalized_name)
        db.add(group)
    else:
        group.name = normalized_name

    db.commit()
    db.refresh(group)
    return {"id": group.id, "name": group.name}


@router.post("/task-types/associate", summary="Associar tipos de tarefa a squads", tags=["Admin"])
def associate_task_types(payload: TaskTypeAssociationPayload, db: Session = Depends(get_db)):
    squads = db.query(Squad).filter(Squad.id.in_(payload.squad_ids)).all()
    if len(squads) != len(set(payload.squad_ids)):
        raise HTTPException(status_code=404, detail="Um ou mais squads nao foram encontrados.")

    task_types = db.query(LegalOneTaskType).filter(LegalOneTaskType.id.in_(payload.task_type_ids)).all()
    if len(task_types) != len(set(payload.task_type_ids)):
        raise HTTPException(status_code=404, detail="Um ou mais tipos de tarefa nao foram encontrados.")

    for task_type in task_types:
        task_type.squads = squads

    db.commit()
    return {"message": "Associacao de tipos de tarefa atualizada com sucesso."}


class RetryBatchRequest(BaseModel):
    item_ids: Optional[List[int]] = None  # se None, retry em todos os FALHA


@router.post(
    "/batch-executions/{execution_id}/retry",
    status_code=202,
    summary="Reprocessar itens falhos de um lote (opcionalmente seletivo por item_ids)",
    tags=["Admin"],
)
def retry_failed_batch_items(
    execution_id: int,
    background_tasks: BackgroundTasks,
    payload: Optional[RetryBatchRequest] = None,
    service: BatchTaskCreationService = Depends(get_batch_task_creation_service),
):
    target_ids = payload.item_ids if payload else None
    logger.info(
        "Reprocessar lote %s (itens=%s)",
        execution_id,
        f"{len(target_ids)} seletivos" if target_ids else "todos FALHA",
    )
    background_tasks.add_task(service.retry_failed_items, execution_id, target_ids)
    return {
        "message": f"Reprocessamento do lote {execution_id} iniciado.",
        "selective": bool(target_ids),
        "count": len(target_ids) if target_ids else None,
    }


@router.get(
    "/batch-executions/{execution_id}/error-groups",
    summary="Agrupa falhas do lote por mensagem de erro (para retry seletivo)",
    tags=["Admin"],
)
def get_batch_error_groups(
    execution_id: int,
    db: Session = Depends(get_db),
):
    """Retorna grupos de falhas com o mesmo error_message e seus item_ids."""
    from app.models.batch_execution import BatchExecution, BatchExecutionItem

    exec_ = db.query(BatchExecution).filter(BatchExecution.id == execution_id).first()
    if not exec_:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    failed = (
        db.query(BatchExecutionItem)
        .filter(
            BatchExecutionItem.execution_id == execution_id,
            BatchExecutionItem.status == "FALHA",
        )
        .all()
    )

    groups: Dict[str, Dict[str, Any]] = {}
    for it in failed:
        key = (it.error_message or "(sem mensagem)").strip()
        bucket = groups.setdefault(key, {"error_message": key, "count": 0, "item_ids": [], "sample_processes": []})
        bucket["count"] += 1
        bucket["item_ids"].append(it.id)
        if len(bucket["sample_processes"]) < 3:
            bucket["sample_processes"].append(it.process_number)

    ordered = sorted(groups.values(), key=lambda g: g["count"], reverse=True)
    return {
        "execution_id": execution_id,
        "total_failed": len(failed),
        "groups": ordered,
    }


# ─── User Management ────────────────────────────────────────────────────────

class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    can_schedule_batch: Optional[bool] = None
    can_use_publications: Optional[bool] = None
    default_office_id: Optional[int] = None


class UserResponseSchema(BaseModel):
    id: int
    email: str
    name: str
    role: str
    can_schedule_batch: bool
    can_use_publications: bool
    default_office_id: Optional[int] = None

    class Config:
        from_attributes = True


@router.get("/users", tags=["Admin"])
def list_users(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """List all users (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    users = db.query(LegalOneUser).order_by(LegalOneUser.name).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "external_id": u.external_id,
            "is_active": u.is_active,
            "role": u.role,
            "can_schedule_batch": u.can_schedule_batch,
            "can_use_publications": u.can_use_publications,
            "default_office_id": u.default_office_id,
            "has_password": u.hashed_password is not None,
            "must_change_password": u.must_change_password,
        }
        for u in users
    ]


@router.patch("/users/{user_id}", tags=["Admin"])
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Update user permissions (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    user = db.query(LegalOneUser).filter(LegalOneUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.role is not None:
        user.role = payload.role
    if payload.can_schedule_batch is not None:
        user.can_schedule_batch = payload.can_schedule_batch
    if payload.can_use_publications is not None:
        user.can_use_publications = payload.can_use_publications
    if payload.default_office_id is not None:
        user.default_office_id = payload.default_office_id

    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "can_schedule_batch": user.can_schedule_batch,
        "can_use_publications": user.can_use_publications,
        "default_office_id": user.default_office_id,
    }


@router.post("/users/{user_id}/activate", tags=["Admin"])
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Activate user and generate temporary password (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    user = db.query(LegalOneUser).filter(LegalOneUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Generate temporary password
    temp_password = auth.generate_temp_password()
    user.hashed_password = auth.get_password_hash(temp_password)
    user.is_active = True
    user.must_change_password = True

    db.commit()
    db.refresh(user)

    # Return the plaintext password ONCE
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "temp_password": temp_password,
        "message": "Esta senha só será exibida uma vez. Repasse-a ao usuário com segurança.",
    }


@router.post("/users/{user_id}/reset-password", tags=["Admin"])
def reset_user_password(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Reset user password (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    user = db.query(LegalOneUser).filter(LegalOneUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Generate temporary password
    temp_password = auth.generate_temp_password()
    user.hashed_password = auth.get_password_hash(temp_password)
    user.must_change_password = True

    db.commit()
    db.refresh(user)

    # Return the plaintext password ONCE
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "temp_password": temp_password,
        "message": "Esta senha só será exibida uma vez. Repasse-a ao usuário com segurança.",
    }


@router.post("/users/{user_id}/deactivate", tags=["Admin"])
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Deactivate user (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    user = db.query(LegalOneUser).filter(LegalOneUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = False
    db.commit()
    db.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_active": user.is_active,
    }


# ─── Saved Filters ──────────────────────────────────────────────────────────

class SavedFilterCreateRequest(BaseModel):
    name: str
    module: str  # "publications", "scheduler", etc.
    filters_json: Dict[str, Any]
    is_default: bool = False


class SavedFilterSchema(BaseModel):
    id: int
    name: str
    module: str
    filters_json: Dict[str, Any]
    is_default: bool

    class Config:
        from_attributes = True


@me_router.get("/me/saved-filters", tags=["User"])
def get_saved_filters(
    module: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Get user's saved filters."""
    query = db.query(SavedFilter).filter(SavedFilter.user_id == current_user.id)
    if module:
        query = query.filter(SavedFilter.module == module)

    filters = query.order_by(SavedFilter.created_at.desc()).all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "module": f.module,
            "filters_json": f.filters_json,
            "is_default": f.is_default,
        }
        for f in filters
    ]


@me_router.post("/me/saved-filters", status_code=201, tags=["User"])
def create_saved_filter(
    payload: SavedFilterCreateRequest,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Create a new saved filter for the user."""
    # If marked as default, unset any existing default for this module
    if payload.is_default:
        db.query(SavedFilter).filter(
            SavedFilter.user_id == current_user.id,
            SavedFilter.module == payload.module,
            SavedFilter.is_default == True,
        ).update({"is_default": False})

    saved_filter = SavedFilter(
        user_id=current_user.id,
        name=payload.name,
        module=payload.module,
        filters_json=payload.filters_json,
        is_default=payload.is_default,
    )
    db.add(saved_filter)
    db.commit()
    db.refresh(saved_filter)

    return {
        "id": saved_filter.id,
        "name": saved_filter.name,
        "module": saved_filter.module,
        "filters_json": saved_filter.filters_json,
        "is_default": saved_filter.is_default,
    }


@me_router.delete("/me/saved-filters/{filter_id}", status_code=204, tags=["User"])
def delete_saved_filter(
    filter_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Delete a saved filter."""
    saved_filter = db.query(SavedFilter).filter(
        SavedFilter.id == filter_id,
        SavedFilter.user_id == current_user.id,
    ).first()

    if not saved_filter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Filter not found")

    db.delete(saved_filter)
    db.commit()
    return None


# ─── User Self-Service Endpoints ───────────────────────────────────────────


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MeResponseSchema(BaseModel):
    id: int
    name: str
    email: str
    role: str
    can_schedule_batch: bool
    can_use_publications: bool
    default_office_id: Optional[int]
    must_change_password: bool

    class Config:
        from_attributes = True


@me_router.get("/me", tags=["User"])
def get_current_user_info(
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Get current user information."""
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "can_schedule_batch": current_user.can_schedule_batch,
        "can_use_publications": current_user.can_use_publications,
        "default_office_id": current_user.default_office_id,
        "must_change_password": current_user.must_change_password,
    }


@me_router.post("/me/change-password", tags=["User"])
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    """Change current user password."""
    # Validate current password
    if not current_user.hashed_password or not auth.verify_password(
        payload.current_password, current_user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Senha atual incorreta.",
        )

    # Validate new password
    auth.validate_password(payload.new_password)

    # Update password
    current_user.hashed_password = auth.get_password_hash(payload.new_password)
    current_user.must_change_password = False

    db.commit()
    db.refresh(current_user)

    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "message": "Senha alterada com sucesso.",
    }
