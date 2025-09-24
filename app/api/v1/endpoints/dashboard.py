# Conteúdo ATUALIZADO para: app/api/v1/endpoints/dashboard.py

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.models.rules import Squad
from app.models.legal_one import LegalOneUser
from app.api.v1.schemas import Squad as SquadSchema, LegalOneUser as LegalOneUserSchema
from typing import List

router = APIRouter()

# Removido:
# templates = Jinja2Templates(directory="templates")

# Endpoint que retorna os dados para a página de gerenciamento de squads
@router.get("/squads", response_model=List[SquadSchema])
def get_squads_data(db: Session = Depends(get_db)):
    """
    Retorna uma lista de todos os squads com seus membros.
    """
    squads = db.query(Squad).order_by(Squad.name).all()
    return squads

# Endpoint que retorna a lista de usuários do Legal One para o dropdown
@router.get("/legal-one-users", response_model=List[LegalOneUserSchema])
def get_legal_one_users_data(db: Session = Depends(get_db)):
    """
    Retorna uma lista de todos os usuários do Legal One.
    """
    users = db.query(LegalOneUser).order_by(LegalOneUser.name).all()
    return users