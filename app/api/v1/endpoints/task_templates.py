"""
Endpoints CRUD para templates de tarefa (classificação × escritório → tarefa).

Rotas:
  GET    /                  → Lista templates (com filtros opcionais)
  GET    /{id}              → Detalhe de um template
  POST   /                  → Cria novo template
  PUT    /{id}              → Atualiza um template
  DELETE /{id}              → Remove um template
  GET    /meta/categories   → Lista categorias/subcategorias disponíveis
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.legal_one import LegalOneOffice, LegalOneTaskSubType, LegalOneTaskType, LegalOneUser
from app.models.task_template import TaskTemplate

router = APIRouter()


# ─── Schemas ────────────────────────────────────

class TaskTemplateBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str
    subcategory: Optional[str] = None
    # None = template global (publicações sem escritório/processo vinculado)
    office_external_id: Optional[int] = None
    task_subtype_external_id: int
    # Opcional: template pode ser criado sem responsável; o modal de
    # criação da tarefa cobra o preenchimento no momento de aplicar.
    responsible_user_external_id: Optional[int] = None
    priority: str = "Normal"
    due_business_days: int = Field(default=3, ge=0, le=365)
    due_date_reference: str = Field(default="publication", pattern=r"^(publication|today)$")
    description_template: Optional[str] = None
    notes_template: Optional[str] = None
    is_active: bool = True
    # 'principal' (default) ou 'assistente'. Quando 'assistente', o frontend
    # de Publicações resolve o assistente via /squads/assistant-of/... antes
    # de mandar o payload pra criação no L1.
    target_role: str = Field(default="principal", pattern="^(principal|assistente)$")


class TaskTemplateCreate(TaskTemplateBase):
    pass


class TaskTemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    office_external_id: Optional[int] = None
    task_subtype_external_id: Optional[int] = None
    responsible_user_external_id: Optional[int] = None
    priority: Optional[str] = None
    due_business_days: Optional[int] = Field(default=None, ge=0, le=365)
    due_date_reference: Optional[str] = Field(default=None, pattern=r"^(publication|today)$")
    description_template: Optional[str] = None
    notes_template: Optional[str] = None
    is_active: Optional[bool] = None
    target_role: Optional[str] = Field(default=None, pattern="^(principal|assistente)$")


class TaskTemplateResponse(TaskTemplateBase):
    id: int
    office_name: Optional[str] = None
    task_subtype_name: Optional[str] = None
    task_type_name: Optional[str] = None
    responsible_user_name: Optional[str] = None

    class Config:
        orm_mode = True


# ─── Helpers ────────────────────────────────────

def _to_response(tmpl: TaskTemplate) -> dict:
    office_name = None
    subtype_name = None
    type_name = None
    user_name = None

    if tmpl.office:
        # Usa path (hierarquia completa) se disponível, senão name
        office_name = tmpl.office.path or tmpl.office.name
    elif tmpl.office_external_id is None:
        office_name = "✦ Publicações sem processo"  # template global
    if tmpl.task_subtype:
        subtype_name = tmpl.task_subtype.name
        if tmpl.task_subtype.parent_type:
            type_name = tmpl.task_subtype.parent_type.name
    if tmpl.responsible_user:
        user_name = tmpl.responsible_user.name

    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "category": tmpl.category,
        "subcategory": tmpl.subcategory,
        "office_external_id": tmpl.office_external_id,
        "office_name": office_name,
        "task_subtype_external_id": tmpl.task_subtype_external_id,
        "task_subtype_name": subtype_name,
        "task_type_name": type_name,
        "responsible_user_external_id": tmpl.responsible_user_external_id,
        "responsible_user_name": user_name,
        "priority": tmpl.priority,
        "due_business_days": tmpl.due_business_days,
        "due_date_reference": tmpl.due_date_reference or "publication",
        "description_template": tmpl.description_template,
        "notes_template": tmpl.notes_template,
        "is_active": tmpl.is_active,
        "target_role": getattr(tmpl, "target_role", None) or "principal",
    }


def _validate_foreign_keys(
    db: Session,
    office_external_id: Optional[int],
    task_subtype_external_id: int,
    responsible_user_external_id: Optional[int],
) -> None:
    # office_external_id pode ser None (template global)
    if office_external_id is not None:
        if not db.query(LegalOneOffice).filter(
            LegalOneOffice.external_id == office_external_id
        ).first():
            raise HTTPException(status_code=400, detail=f"Escritório {office_external_id} não encontrado.")

    if not db.query(LegalOneTaskSubType).filter(
        LegalOneTaskSubType.external_id == task_subtype_external_id
    ).first():
        raise HTTPException(status_code=400, detail=f"Subtipo de tarefa {task_subtype_external_id} não encontrado.")

    # Responsável é opcional; só valida FK se foi informado.
    if responsible_user_external_id is not None:
        if not db.query(LegalOneUser).filter(
            LegalOneUser.external_id == responsible_user_external_id
        ).first():
            raise HTTPException(status_code=400, detail=f"Usuário {responsible_user_external_id} não encontrado.")


# ─── Endpoints ──────────────────────────────────

@router.get("/", response_model=List[TaskTemplateResponse])
def list_templates(
    category: Optional[str] = Query(None),
    subcategory: Optional[str] = Query(None),
    office_external_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    """Lista templates com filtros opcionais."""
    q = db.query(TaskTemplate)

    if category is not None:
        q = q.filter(TaskTemplate.category == category)
    if subcategory is not None:
        q = q.filter(TaskTemplate.subcategory == subcategory)
    if office_external_id is not None:
        q = q.filter(TaskTemplate.office_external_id == office_external_id)
    if is_active is not None:
        q = q.filter(TaskTemplate.is_active == is_active)

    # Recém-criados primeiro: quando o operador salva um template novo
    # pela UI, ele espera ver no topo da lista imediatamente. Ordem secundária
    # mantém a organização alfabética por categoria dentro de um mesmo dia.
    templates = q.order_by(
        TaskTemplate.created_at.desc(),
        TaskTemplate.category,
        TaskTemplate.subcategory,
        TaskTemplate.name,
    ).all()
    return [_to_response(t) for t in templates]


@router.get("/{template_id}", response_model=TaskTemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db)):
    """Retorna detalhe de um template."""
    tmpl = db.query(TaskTemplate).filter(TaskTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    return _to_response(tmpl)


@router.post("/", response_model=TaskTemplateResponse, status_code=201)
def create_template(payload: TaskTemplateCreate, db: Session = Depends(get_db)):
    """Cria um novo template de tarefa."""
    _validate_foreign_keys(
        db,
        payload.office_external_id,
        payload.task_subtype_external_id,
        payload.responsible_user_external_id,
    )

    # Múltiplos templates por (category, subcategory, office) são permitidos
    # — cada um gera uma tarefa diferente no agendamento (ver docstring do
    # modelo TaskTemplate). Só bloqueamos duplicata *exata*: mesma
    # classificação + mesmo escritório + mesmo subtipo de tarefa, já que
    # dois templates idênticos gerariam a mesma tarefa duas vezes.
    existing = db.query(TaskTemplate).filter(
        TaskTemplate.category == payload.category,
        TaskTemplate.subcategory == payload.subcategory,
        TaskTemplate.office_external_id == payload.office_external_id,
        TaskTemplate.task_subtype_external_id == payload.task_subtype_external_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Já existe um template para esta classificação, escritório e "
                "subtipo de tarefa. Para gerar uma segunda tarefa na mesma "
                "classificação, escolha um subtipo de tarefa diferente."
            ),
        )

    tmpl = TaskTemplate(**payload.dict())
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return _to_response(tmpl)


@router.put("/{template_id}", response_model=TaskTemplateResponse)
def update_template(
    template_id: int,
    payload: TaskTemplateUpdate,
    db: Session = Depends(get_db),
):
    """Atualiza um template existente."""
    tmpl = db.query(TaskTemplate).filter(TaskTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template não encontrado.")

    updates = payload.dict(exclude_unset=True)

    # Valida FKs se estiverem sendo atualizadas
    if any(k in updates for k in ("office_external_id", "task_subtype_external_id", "responsible_user_external_id")):
        _validate_foreign_keys(
            db,
            updates.get("office_external_id", tmpl.office_external_id),
            updates.get("task_subtype_external_id", tmpl.task_subtype_external_id),
            updates.get("responsible_user_external_id", tmpl.responsible_user_external_id),
        )

    for k, v in updates.items():
        setattr(tmpl, k, v)

    db.commit()
    db.refresh(tmpl)
    return _to_response(tmpl)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, db: Session = Depends(get_db)):
    """Remove um template."""
    tmpl = db.query(TaskTemplate).filter(TaskTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    db.delete(tmpl)
    db.commit()
    return None


@router.get("/meta/task-types")
def list_task_types(db: Session = Depends(get_db)):
    """Lista tipos e subtipos de tarefa com seus external_ids (para uso no formulário de template)."""
    from sqlalchemy.orm import joinedload
    types = (
        db.query(LegalOneTaskType)
        .options(joinedload(LegalOneTaskType.subtypes))
        .filter(LegalOneTaskType.is_active == True)
        .order_by(LegalOneTaskType.name)
        .all()
    )
    return [
        {
            "external_id": t.external_id,
            "name": t.name,
            "subtypes": [
                {"external_id": s.external_id, "name": s.name}
                for s in sorted(t.subtypes, key=lambda x: x.name)
                if s.is_active
            ],
        }
        for t in types
    ]


@router.get("/meta/users")
def list_users(db: Session = Depends(get_db)):
    """Lista usuários ativos com seus external_ids (para uso no formulário de template)."""
    users = (
        db.query(LegalOneUser)
        .filter(LegalOneUser.is_active == True)
        .order_by(LegalOneUser.name)
        .all()
    )
    return [{"external_id": u.external_id, "name": u.name, "email": u.email} for u in users]


@router.get("/meta/categories")
def list_categories(
    office_external_id: Optional[int] = Query(
        None,
        description="Se informado, aplica os overrides (excluir / adicionar customizada) do escritório.",
    ),
    db: Session = Depends(get_db),
):
    """Lista as categorias e subcategorias disponíveis.

    - Sem `office_external_id`: retorna a taxonomia base do classificador.
    - Com `office_external_id`: retorna a taxonomia **efetiva** do escritório,
      ou seja, já com exclusões removidas e include_custom adicionados.
    """
    try:
        from app.services.classifier.taxonomy import CLASSIFICATION_TREE  # noqa: WPS433
    except Exception:
        return {"categories": []}

    try:
        tree: dict[str, list[str]] = {k: list(v) for k, v in CLASSIFICATION_TREE.items()}

        if office_external_id is not None:
            try:
                from app.services.classifier.prompts import load_office_overrides  # noqa: WPS433

                excluded, custom_additions = load_office_overrides(db, office_external_id)

                # Exclusões: subcategory=None remove a categoria inteira
                cats_to_remove: set[str] = set()
                for cat, sub in excluded:
                    if sub is None:
                        cats_to_remove.add(cat)
                    elif cat in tree and sub in tree[cat]:
                        tree[cat].remove(sub)
                for cat in cats_to_remove:
                    tree.pop(cat, None)

                # Adições customizadas
                for item in custom_additions:
                    cat = item.get("category", "")
                    sub = item.get("subcategory")
                    if not cat:
                        continue
                    if cat not in tree:
                        tree[cat] = []
                    if sub and sub not in tree[cat]:
                        tree[cat].append(sub)
            except Exception:
                # Falha ao aplicar overrides: cai para a árvore base, sem quebrar a página.
                tree = {k: list(v) for k, v in CLASSIFICATION_TREE.items()}

        return {
            "categories": [
                {"category": cat, "subcategories": list(subs) if subs else []}
                for cat, subs in tree.items()
            ]
        }
    except Exception:
        return {"categories": []}
