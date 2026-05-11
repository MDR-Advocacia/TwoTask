"""Endpoints admin pra CRUD de API keys da Base Processual (Chunk 6).

Apenas role=admin via JWT — `require_admin` reutilizado de base_processual.py.

Plaintext da chave so' aparece UMA VEZ: na resposta do POST (criacao) e
do POST /{id}/regenerate. Operador copia + guarda em local seguro; nao
tem recuperacao depois (so regerar — invalida a anterior).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.base_processual import require_admin
from app.api.v1.schemas import (
    BaseProcessualApiKeyCreatePayload,
    BaseProcessualApiKeyCreateResponse,
    BaseProcessualApiKeyListResponse,
    BaseProcessualApiKeyOut,
)
from app.core.dependencies import get_db
from app.models.base_processual import BaseProcessualApiKey
from app.models.legal_one import LegalOneUser
from app.services.base_processual.api_key_service import (
    VALID_SCOPES,
    generate_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin/base-processual/api-keys",
    tags=["Base Processual"],
)


@router.get("", response_model=BaseProcessualApiKeyListResponse)
def list_api_keys(
    include_revoked: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    q = db.query(BaseProcessualApiKey).order_by(
        BaseProcessualApiKey.id.desc()
    )
    if not include_revoked:
        q = q.filter(BaseProcessualApiKey.revoked_at.is_(None))
    total = q.count()
    items = q.limit(limit).offset(offset).all()
    return BaseProcessualApiKeyListResponse(
        total=total,
        items=[BaseProcessualApiKeyOut.model_validate(k) for k in items],
    )


@router.post("", response_model=BaseProcessualApiKeyCreateResponse)
def create_api_key(
    payload: BaseProcessualApiKeyCreatePayload,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Cria chave nova. Plaintext retornado UMA VEZ — guarde com cuidado."""
    nome = (payload.nome or "").strip()
    if not nome:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campo 'nome' obrigatorio.",
        )
    scope = (payload.scope or "").strip()
    if scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scope invalido: {scope!r}. Validos: {list(VALID_SCOPES)}",
        )

    plaintext, prefix, key_hash = generate_key()
    new_key = BaseProcessualApiKey(
        nome=nome,
        key_hash=key_hash,
        key_prefix=prefix,
        scope=scope,
        rate_limit_per_min=payload.rate_limit_per_min or 60,
        created_by_user_id=user.id,
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    return BaseProcessualApiKeyCreateResponse(
        api_key=BaseProcessualApiKeyOut.model_validate(new_key),
        plaintext=plaintext,
    )


@router.post(
    "/{key_id}/regenerate",
    response_model=BaseProcessualApiKeyCreateResponse,
)
def regenerate_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Regenera o plaintext da chave (substitui hash + prefix). Invalida o anterior."""
    k = (
        db.query(BaseProcessualApiKey)
        .filter(BaseProcessualApiKey.id == key_id)
        .first()
    )
    if k is None:
        raise HTTPException(
            status_code=404, detail=f"Chave #{key_id} nao encontrada."
        )
    if k.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Chave #{key_id} esta revogada desde {k.revoked_at}. "
                "Crie uma chave nova em vez de regenerar revogada."
            ),
        )
    plaintext, prefix, key_hash = generate_key()
    k.key_hash = key_hash
    k.key_prefix = prefix
    db.commit()
    db.refresh(k)
    return BaseProcessualApiKeyCreateResponse(
        api_key=BaseProcessualApiKeyOut.model_validate(k),
        plaintext=plaintext,
    )


@router.delete("/{key_id}", response_model=BaseProcessualApiKeyOut)
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    user: LegalOneUser = Depends(require_admin),
):
    """Revoga a chave (soft — preserva audit). Hits futuros da chave dao 403."""
    k = (
        db.query(BaseProcessualApiKey)
        .filter(BaseProcessualApiKey.id == key_id)
        .first()
    )
    if k is None:
        raise HTTPException(
            status_code=404, detail=f"Chave #{key_id} nao encontrada."
        )
    if k.revoked_at is None:
        k.revoked_at = datetime.utcnow()
        db.commit()
        db.refresh(k)
    return BaseProcessualApiKeyOut.model_validate(k)
