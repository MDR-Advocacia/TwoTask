# app/api/v1/endpoints/users.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.core.dependencies import get_db
from app.models import legal_one as legal_one_models, rules as rules_models
from app.api.v1 import schemas

router = APIRouter()

@router.get("/with-squads", response_model=List[schemas.UserWithSquads])
def get_users_with_squads(db: Session = Depends(get_db)):
    """
    Busca todos os usuários ativos do Legal One e, para cada um,
    inclui uma lista dos squads e seus respectivos setores.
    """
    users = (
        db.query(legal_one_models.LegalOneUser)
        .options(
            joinedload(legal_one_models.LegalOneUser.squad_members)
            .joinedload(rules_models.SquadMember.squad)
            .joinedload(rules_models.Squad.sector)
        )
        .filter(legal_one_models.LegalOneUser.is_active == True)
        .order_by(legal_one_models.LegalOneUser.name)
        .all()
    )

    # if not users:
    #     raise HTTPException(status_code=404, detail="Nenhum usuário ativo encontrado.")

    # O schema UserWithSquads fará a transformação dos dados
    return users