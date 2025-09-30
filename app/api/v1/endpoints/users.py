# app/api/v1/endpoints/users.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.core.dependencies import get_db
from app.models import legal_one as legal_one_models
from app.api.v1 import schemas

router = APIRouter()

@router.get("/with-squads", response_model=List[schemas.UserWithSquads])
def get_users_with_squads(db: Session = Depends(get_db)):
    """
    Busca todos os usuários ativos do Legal One e, para cada um,
    inclui uma lista dos squads aos quais pertencem.
    """
    users = (
        db.query(legal_one_models.LegalOneUser)
        .options(joinedload(legal_one_models.LegalOneUser.squad_members).joinedload(legal_one_models.SquadMember.squad))
        .filter(legal_one_models.LegalOneUser.is_active == True)
        .order_by(legal_one_models.LegalOneUser.name)
        .all()
    )

    if not users:
        raise HTTPException(status_code=404, detail="Nenhum usuário ativo encontrado.")

    # A estrutura do schema fará a transformação dos dados automaticamente
    return users