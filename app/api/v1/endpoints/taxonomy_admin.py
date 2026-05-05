"""Admin: gerenciamento da taxonomia de classificações de publicações.

CRUD em `classification_categories` / `classification_subcategories` +
helper Sonnet pra estruturar cadastros novos. Toda mutação chama
`invalidate_taxonomy_cache()` pra que o classifier veja a mudança no
próximo request (em vez de esperar TTL=60s).

Soft delete via `is_active=False` — preserva histórico de classificações
antigas que apontam pra categoria/subcategoria descontinuada (não
quebra reports/analytics).

Sonnet helper (`POST /admin/taxonomy/suggest`) recebe nome+descrição e
devolve campos estruturados (polo padrão, prazo CPC, exemplo de
publicação) pra que o admin não precise pesquisar CPC sozinho.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core import auth
from app.core.dependencies import get_db
from app.models.classification_taxonomy import (
    ClassificationCategory,
    ClassificationSubcategory,
)
from app.models.legal_one import LegalOneUser
from app.services.classifier.ai_client import AnthropicClassifierClient
from app.services.classifier.taxonomy import invalidate_taxonomy_cache

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────


class SubcategoryPayload(BaseModel):
    """Payload de create/update de subcategoria.

    Campos opcionais: omitir (None) = manter o que está no DB ao
    atualizar; usar default ao criar.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    default_polo: Optional[str] = None  # 'autor' | 'reu' | 'ambos' | None
    default_prazo_dias: Optional[int] = None
    default_prazo_tipo: Optional[str] = None  # 'util' | 'corrido' | None
    default_prazo_fundamentacao: Optional[str] = None
    example_publication: Optional[str] = None
    example_response_json: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class CategoryPayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_polo: Optional[str] = None
    default_prazo_dias: Optional[int] = None
    default_prazo_tipo: Optional[str] = None
    default_prazo_fundamentacao: Optional[str] = None
    example_publication: Optional[str] = None
    example_response_json: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class SubcategorySchema(BaseModel):
    id: int
    category_id: int
    name: str
    description: Optional[str] = None
    default_polo: Optional[str] = None
    default_prazo_dias: Optional[int] = None
    default_prazo_tipo: Optional[str] = None
    default_prazo_fundamentacao: Optional[str] = None
    example_publication: Optional[str] = None
    example_response_json: Optional[str] = None
    display_order: int
    is_active: bool

    class Config:
        from_attributes = True


class CategorySchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    default_polo: Optional[str] = None
    default_prazo_dias: Optional[int] = None
    default_prazo_tipo: Optional[str] = None
    default_prazo_fundamentacao: Optional[str] = None
    example_publication: Optional[str] = None
    example_response_json: Optional[str] = None
    display_order: int
    is_active: bool
    subcategories: list[SubcategorySchema] = Field(default_factory=list)

    class Config:
        from_attributes = True


class SuggestRequest(BaseModel):
    """Input do helper Sonnet.

    `parent_category_name` deve vir quando o admin estiver cadastrando
    uma subcategoria — dá contexto pra IA gerar prazo/polo coerentes
    com a categoria pai (ex.: subcategorias de Sentença normalmente são
    do polo réu, prazo 15 dias úteis pra recurso).
    """

    name: str = Field(..., min_length=2, description="Nome da categoria/subcategoria")
    parent_category_name: Optional[str] = Field(
        None,
        description="Nome da categoria pai (preencher quando for subcategoria).",
    )
    hint: Optional[str] = Field(
        None,
        description="Texto livre do admin descrevendo quando aplicar/exemplo prático.",
    )


class SuggestResponse(BaseModel):
    description: Optional[str] = None
    default_polo: Optional[str] = None
    default_prazo_dias: Optional[int] = None
    default_prazo_tipo: Optional[str] = None
    default_prazo_fundamentacao: Optional[str] = None
    example_publication: Optional[str] = None
    example_response_summary: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _require_admin(current_user: LegalOneUser) -> None:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


def _serialize_category(cat: ClassificationCategory) -> dict[str, Any]:
    return {
        "id": cat.id,
        "name": cat.name,
        "description": cat.description,
        "default_polo": cat.default_polo,
        "default_prazo_dias": cat.default_prazo_dias,
        "default_prazo_tipo": cat.default_prazo_tipo,
        "default_prazo_fundamentacao": cat.default_prazo_fundamentacao,
        "example_publication": cat.example_publication,
        "example_response_json": cat.example_response_json,
        "display_order": cat.display_order,
        "is_active": cat.is_active,
        "subcategories": [_serialize_subcategory(s) for s in cat.subcategories],
    }


def _serialize_subcategory(sub: ClassificationSubcategory) -> dict[str, Any]:
    return {
        "id": sub.id,
        "category_id": sub.category_id,
        "name": sub.name,
        "description": sub.description,
        "default_polo": sub.default_polo,
        "default_prazo_dias": sub.default_prazo_dias,
        "default_prazo_tipo": sub.default_prazo_tipo,
        "default_prazo_fundamentacao": sub.default_prazo_fundamentacao,
        "example_publication": sub.example_publication,
        "example_response_json": sub.example_response_json,
        "display_order": sub.display_order,
        "is_active": sub.is_active,
    }


def _apply_payload(target: Any, payload: dict[str, Any], allow_name: bool = True) -> None:
    """Aplica campos do payload no target ORM, ignorando None.

    `allow_name=False` pra rotas que não devem permitir rename (futuro).
    """
    for key, value in payload.items():
        if value is None:
            continue
        if key == "name" and not allow_name:
            continue
        setattr(target, key, value)


# ─────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/taxonomy",
    summary="Lista taxonomia completa (categorias + subcategorias)",
    tags=["Admin: Taxonomia"],
)
def list_taxonomy(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)

    query = db.query(ClassificationCategory).options(
        joinedload(ClassificationCategory.subcategories),
    )
    if not include_inactive:
        query = query.filter(ClassificationCategory.is_active.is_(True))

    cats = query.order_by(
        ClassificationCategory.display_order,
        ClassificationCategory.name,
    ).all()

    # Filtra subcategorias inativas se include_inactive=False
    result = []
    for cat in cats:
        cat_dict = _serialize_category(cat)
        if not include_inactive:
            cat_dict["subcategories"] = [
                s for s in cat_dict["subcategories"] if s["is_active"]
            ]
        result.append(cat_dict)
    return {"categories": result}


# ─────────────────────────────────────────────────────────────────────
# CATEGORIES — CRUD
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/taxonomy/categories",
    status_code=201,
    summary="Cria nova categoria",
    tags=["Admin: Taxonomia"],
)
def create_category(
    payload: CategoryPayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obrigatório.")

    # Unique check
    existing = (
        db.query(ClassificationCategory)
        .filter(ClassificationCategory.name == name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Já existe categoria com o nome '{name}'.",
        )

    # Ordem default = max+1 (vai pro fim)
    if payload.display_order is None:
        max_order = (
            db.query(ClassificationCategory.display_order)
            .order_by(ClassificationCategory.display_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else 0
    else:
        next_order = payload.display_order

    cat = ClassificationCategory(
        name=name,
        description=payload.description,
        default_polo=payload.default_polo,
        default_prazo_dias=payload.default_prazo_dias,
        default_prazo_tipo=payload.default_prazo_tipo,
        default_prazo_fundamentacao=payload.default_prazo_fundamentacao,
        example_publication=payload.example_publication,
        example_response_json=payload.example_response_json,
        display_order=next_order,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    invalidate_taxonomy_cache()
    logger.info("Taxonomia: categoria criada id=%s name=%s", cat.id, cat.name)
    return _serialize_category(cat)


@router.patch(
    "/taxonomy/categories/{category_id}",
    summary="Atualiza categoria existente",
    tags=["Admin: Taxonomia"],
)
def update_category(
    category_id: int,
    payload: CategoryPayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)

    cat = (
        db.query(ClassificationCategory)
        .filter(ClassificationCategory.id == category_id)
        .first()
    )
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    data = payload.model_dump(exclude_unset=True)

    # Se está renomeando, valida unicidade
    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Nome não pode ficar vazio.")
        if new_name != cat.name:
            dup = (
                db.query(ClassificationCategory)
                .filter(
                    ClassificationCategory.name == new_name,
                    ClassificationCategory.id != category_id,
                )
                .first()
            )
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=f"Já existe outra categoria com o nome '{new_name}'.",
                )
        data["name"] = new_name

    _apply_payload(cat, data)
    db.commit()
    db.refresh(cat)
    invalidate_taxonomy_cache()
    logger.info("Taxonomia: categoria atualizada id=%s", cat.id)
    return _serialize_category(cat)


@router.delete(
    "/taxonomy/categories/{category_id}",
    summary="Inativa categoria (soft delete)",
    tags=["Admin: Taxonomia"],
)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)

    cat = (
        db.query(ClassificationCategory)
        .filter(ClassificationCategory.id == category_id)
        .first()
    )
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    cat.is_active = False
    db.commit()
    invalidate_taxonomy_cache()
    logger.info("Taxonomia: categoria inativada id=%s", cat.id)
    return {"id": cat.id, "is_active": cat.is_active}


@router.post(
    "/taxonomy/categories/{category_id}/restore",
    summary="Reativa categoria inativada",
    tags=["Admin: Taxonomia"],
)
def restore_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    cat = (
        db.query(ClassificationCategory)
        .filter(ClassificationCategory.id == category_id)
        .first()
    )
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    cat.is_active = True
    db.commit()
    invalidate_taxonomy_cache()
    logger.info("Taxonomia: categoria reativada id=%s", cat.id)
    return _serialize_category(cat)


# ─────────────────────────────────────────────────────────────────────
# SUBCATEGORIES — CRUD
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/taxonomy/categories/{category_id}/subcategories",
    status_code=201,
    summary="Cria subcategoria dentro de uma categoria",
    tags=["Admin: Taxonomia"],
)
def create_subcategory(
    category_id: int,
    payload: SubcategoryPayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)

    cat = (
        db.query(ClassificationCategory)
        .filter(ClassificationCategory.id == category_id)
        .first()
    )
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obrigatório.")

    # Unique por categoria
    dup = (
        db.query(ClassificationSubcategory)
        .filter(
            ClassificationSubcategory.category_id == category_id,
            ClassificationSubcategory.name == name,
        )
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"Subcategoria '{name}' já existe nessa categoria.",
        )

    if payload.display_order is None:
        max_order = (
            db.query(ClassificationSubcategory.display_order)
            .filter(ClassificationSubcategory.category_id == category_id)
            .order_by(ClassificationSubcategory.display_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else 0
    else:
        next_order = payload.display_order

    sub = ClassificationSubcategory(
        category_id=category_id,
        name=name,
        description=payload.description,
        default_polo=payload.default_polo,
        default_prazo_dias=payload.default_prazo_dias,
        default_prazo_tipo=payload.default_prazo_tipo,
        default_prazo_fundamentacao=payload.default_prazo_fundamentacao,
        example_publication=payload.example_publication,
        example_response_json=payload.example_response_json,
        display_order=next_order,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    invalidate_taxonomy_cache()
    logger.info(
        "Taxonomia: subcategoria criada id=%s cat=%s name=%s",
        sub.id, category_id, sub.name,
    )
    return _serialize_subcategory(sub)


@router.patch(
    "/taxonomy/subcategories/{subcategory_id}",
    summary="Atualiza subcategoria existente",
    tags=["Admin: Taxonomia"],
)
def update_subcategory(
    subcategory_id: int,
    payload: SubcategoryPayload,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)

    sub = (
        db.query(ClassificationSubcategory)
        .filter(ClassificationSubcategory.id == subcategory_id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subcategoria não encontrada.")

    data = payload.model_dump(exclude_unset=True)

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Nome não pode ficar vazio.")
        if new_name != sub.name:
            dup = (
                db.query(ClassificationSubcategory)
                .filter(
                    ClassificationSubcategory.category_id == sub.category_id,
                    ClassificationSubcategory.name == new_name,
                    ClassificationSubcategory.id != subcategory_id,
                )
                .first()
            )
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=f"Já existe outra subcategoria '{new_name}' nessa categoria.",
                )
        data["name"] = new_name

    _apply_payload(sub, data)
    db.commit()
    db.refresh(sub)
    invalidate_taxonomy_cache()
    logger.info("Taxonomia: subcategoria atualizada id=%s", sub.id)
    return _serialize_subcategory(sub)


@router.delete(
    "/taxonomy/subcategories/{subcategory_id}",
    summary="Inativa subcategoria (soft delete)",
    tags=["Admin: Taxonomia"],
)
def delete_subcategory(
    subcategory_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    sub = (
        db.query(ClassificationSubcategory)
        .filter(ClassificationSubcategory.id == subcategory_id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subcategoria não encontrada.")
    sub.is_active = False
    db.commit()
    invalidate_taxonomy_cache()
    logger.info("Taxonomia: subcategoria inativada id=%s", sub.id)
    return {"id": sub.id, "is_active": sub.is_active}


@router.post(
    "/taxonomy/subcategories/{subcategory_id}/restore",
    summary="Reativa subcategoria inativada",
    tags=["Admin: Taxonomia"],
)
def restore_subcategory(
    subcategory_id: int,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    sub = (
        db.query(ClassificationSubcategory)
        .filter(ClassificationSubcategory.id == subcategory_id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subcategoria não encontrada.")
    sub.is_active = True
    db.commit()
    invalidate_taxonomy_cache()
    logger.info("Taxonomia: subcategoria reativada id=%s", sub.id)
    return _serialize_subcategory(sub)


# ─────────────────────────────────────────────────────────────────────
# Sonnet helper
# ─────────────────────────────────────────────────────────────────────


_SUGGEST_SYSTEM_PROMPT = """Você é um assistente jurídico que ajuda a estruturar uma taxonomia de classificações de publicações judiciais brasileiras.

Quando receber o nome de uma categoria ou subcategoria nova (e opcionalmente uma descrição/dica do admin), retorne um JSON estruturado com os campos abaixo. Se não souber algum campo com confiança razoável, retorne null nele em vez de inventar.

Campos do JSON de saída:
- description: 1-3 frases descrevendo quando essa classificação se aplica (em pt-BR, voltado pro operador jurídico).
- default_polo: o polo que normalmente atua nessa publicação. Valores válidos: "autor", "reu", "ambos" ou null.
- default_prazo_dias: quantidade de dias do prazo padrão pra agir (ex.: 15 pra contestação). Inteiro ou null.
- default_prazo_tipo: "util" (dias úteis, padrão CPC) ou "corrido" ou null.
- default_prazo_fundamentacao: artigo do CPC ou lei que fundamenta o prazo. Ex.: "Art. 335 do CPC" ou "Art. 1.003, §5º do CPC". String ou null.
- example_publication: trecho realista (1-3 frases) de uma publicação judicial que se classificaria assim. Use placeholders como [PROCESSO], [JUIZ], [PARTE].
- example_response_summary: 1 frase descrevendo o que o operador deve fazer ao receber essa publicação.

Retorne APENAS o JSON puro, sem ```markdown nem texto antes/depois."""


def _build_suggest_user_message(payload: SuggestRequest) -> str:
    parts = [f"Nome: {payload.name}"]
    if payload.parent_category_name:
        parts.append(f"Categoria pai: {payload.parent_category_name}")
        parts.append(
            "(Estou cadastrando uma SUBCATEGORIA dentro dessa categoria pai.)"
        )
    else:
        parts.append("(Estou cadastrando uma CATEGORIA nova de primeiro nível.)")
    if payload.hint:
        parts.append(f"Contexto/dica do admin: {payload.hint}")
    parts.append("\nGere o JSON estruturado conforme as instruções do sistema.")
    return "\n".join(parts)


@router.post(
    "/taxonomy/suggest",
    summary="Sugere campos estruturados via Sonnet pra cadastro novo",
    tags=["Admin: Taxonomia"],
)
async def suggest_taxonomy_fields(
    payload: SuggestRequest,
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)

    try:
        client = AnthropicClassifierClient()
    except ValueError as exc:
        # ANTHROPIC_API_KEY não configurada
        raise HTTPException(status_code=503, detail=str(exc))

    user_message = _build_suggest_user_message(payload)

    try:
        # `classify` parsea como classification response (espera "categoria"),
        # então chamamos o endpoint Anthropic direto via httpx pra ter
        # liberdade no formato de resposta.
        import httpx
        from app.services.classifier.ai_client import (
            ANTHROPIC_API_URL, ANTHROPIC_API_VERSION,
        )
        from app.core.config import settings

        api_payload = {
            "model": settings.classifier_model,
            "max_tokens": 1024,
            "temperature": 0.2,  # leve criatividade pro example_publication
            "system": _SUGGEST_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        }
        async with httpx.AsyncClient(timeout=60.0) as http_client:
            response = await http_client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": client.api_key,
                    "anthropic-version": ANTHROPIC_API_VERSION,
                    "content-type": "application/json",
                },
                json=api_payload,
            )
        if response.status_code != 200:
            logger.error(
                "Sonnet suggest: HTTP %s — %s",
                response.status_code,
                response.text[:300],
            )
            raise HTTPException(
                status_code=502,
                detail=f"Erro na API Anthropic (HTTP {response.status_code}).",
            )

        data = response.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise HTTPException(status_code=502, detail="Resposta vazia da IA.")

        raw_text = content_blocks[0].get("text", "").strip()
        # Tira fences markdown se vierem
        if raw_text.startswith("```"):
            lines = [
                ln for ln in raw_text.split("\n")
                if not ln.strip().startswith("```")
            ]
            raw_text = "\n".join(lines).strip()

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("Sonnet suggest: JSON inválido — %s", raw_text[:300])
            raise HTTPException(
                status_code=502,
                detail="A IA retornou resposta não-JSON. Tente novamente.",
            )

        # Normaliza campos — só passa adiante o que conhecemos
        suggestion = {
            "description": parsed.get("description"),
            "default_polo": parsed.get("default_polo"),
            "default_prazo_dias": parsed.get("default_prazo_dias"),
            "default_prazo_tipo": parsed.get("default_prazo_tipo"),
            "default_prazo_fundamentacao": parsed.get("default_prazo_fundamentacao"),
            "example_publication": parsed.get("example_publication"),
            "example_response_summary": parsed.get("example_response_summary"),
        }
        # Coerção leve de tipos
        if isinstance(suggestion["default_prazo_dias"], str):
            try:
                suggestion["default_prazo_dias"] = int(suggestion["default_prazo_dias"])
            except (ValueError, TypeError):
                suggestion["default_prazo_dias"] = None
        # Polo: aceita só os 3 valores
        polo = suggestion.get("default_polo")
        if polo and str(polo).lower() not in ("autor", "reu", "réu", "ambos"):
            suggestion["default_polo"] = None
        elif polo:
            polo_norm = str(polo).lower().replace("réu", "reu")
            suggestion["default_polo"] = polo_norm
        # Tipo de prazo
        tipo = suggestion.get("default_prazo_tipo")
        if tipo and str(tipo).lower() not in ("util", "útil", "corrido"):
            suggestion["default_prazo_tipo"] = None
        elif tipo:
            suggestion["default_prazo_tipo"] = str(tipo).lower().replace("útil", "util")

        return suggestion

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Sonnet suggest: falha inesperada")
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar a IA: {exc}",
        )


# ─────────────────────────────────────────────────────────────────────
# Cache info
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/taxonomy/cache-info",
    summary="Info do cache de taxonomia (TTL/idade) — usado pela UI pra barra de progresso",
    tags=["Admin: Taxonomia"],
)
def get_taxonomy_cache_info(
    current_user: LegalOneUser = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    from app.services.classifier import taxonomy as tax_mod

    ttl = tax_mod._CACHE_TTL_SECONDS
    age = 0.0
    has_cache = tax_mod._TREE_CACHE is not None
    if has_cache:
        import time as _time
        age = _time.monotonic() - tax_mod._TREE_CACHE_AT
    return {
        "ttl_seconds": ttl,
        "age_seconds": age,
        "remaining_seconds": max(0.0, ttl - age),
        "has_cache": has_cache,
    }
