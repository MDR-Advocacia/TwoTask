# app/api/v1/endpoints/squads.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.models import rules as rules_models
from app.models import legal_one as legal_one_models
from app.api.v1 import schemas

# --- A LINHA QUE FALTAVA ---
router = APIRouter()
# -------------------------

@router.get("", response_model=List[schemas.Squad])
def get_squads(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os squads e membros ATIVOS.
    """
    squads = (
        db.query(rules_models.Squad)
        .filter(rules_models.Squad.is_active == True)
        .all()
    )
    if not squads:
        raise HTTPException(status_code=404, detail="Nenhum squad ativo encontrado.")
    
    # Filtra membros inativos na resposta
    active_squads_data = []
    for squad in squads:
        active_members = [member for member in squad.members if member.is_active]
        squad.members = active_members
        active_squads_data.append(squad)

    return active_squads_data

@router.get("/legal-one-users", response_model=List[schemas.LegalOneUser])
def get_legal_one_users(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os usuários do Legal One para
    popular os dropdowns de associação no frontend.
    """
    users = db.query(legal_one_models.LegalOneUser).order_by(legal_one_models.LegalOneUser.name).all()
    if not users:
        raise HTTPException(status_code=404, detail="Nenhum usuário do Legal One encontrado.")
    return users

@router.put("/members/link", response_model=schemas.SquadMember)
def update_squad_member_link(
    link_data: schemas.SquadMemberLinkUpdate,
    db: Session = Depends(get_db)
):
    """
    Atualiza o vínculo entre um membro de squad e um usuário do Legal One.
    """
    member = db.query(rules_models.SquadMember).filter(rules_models.SquadMember.id == link_data.squad_member_id).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Membro do Squad não encontrado.")

    member.legal_one_user_id = link_data.legal_one_user_id if link_data.legal_one_user_id else None
    
    db.commit()
    db.refresh(member)
    
    return member