# app/api/v1/endpoints/squads.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.models import legal_one as legal_one_models
from app.api.v1 import schemas
from app.services.squad_service import SquadService

router = APIRouter()

def get_squad_service(db: Session = Depends(get_db)) -> SquadService:
    """
    Dependência para injetar o SquadService nos endpoints.
    """
    return SquadService(db)

@router.post("", response_model=schemas.Squad, status_code=201)
def create_squad(
    squad_data: schemas.SquadCreateSchema,
    service: SquadService = Depends(get_squad_service)
):
    """
    Cria um novo squad.
    """
    try:
        squad = service.create_squad(squad_data)
        return squad
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

from typing import Optional

@router.get("", response_model=List[schemas.Squad])
def get_squads(
    sector_id: Optional[int] = None,
    service: SquadService = Depends(get_squad_service)
):
    """
    Endpoint para buscar todos os squads e membros ATIVOS.
    Pode ser filtrado por `sector_id`.
    """
    squads = service.get_all_squads(sector_id=sector_id)
    
    # Filtra membros inativos (com base no status do usuário do Legal One) na resposta
    active_squads_data = []
    for squad in squads:
        active_members = [
            member for member in squad.members if member.user and member.user.is_active
        ]
        squad.members = active_members
        active_squads_data.append(squad)

    return active_squads_data

@router.put("/{squad_id}", response_model=schemas.Squad)
def update_squad(
    squad_id: int,
    squad_data: schemas.SquadUpdateSchema,
    service: SquadService = Depends(get_squad_service)
):
    """
    Atualiza um squad existente (nome e/ou membros).
    """
    try:
        updated_squad = service.update_squad(squad_id, squad_data)
        if not updated_squad:
            raise HTTPException(status_code=404, detail=f"Squad com ID {squad_id} não encontrado.")
        return updated_squad
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{squad_id}", status_code=204)
def deactivate_squad(
    squad_id: int,
    service: SquadService = Depends(get_squad_service)
):
    """
    Desativa um squad, marcando-o como inativo.
    """
    deactivated_squad = service.deactivate_squad(squad_id)
    if not deactivated_squad:
        raise HTTPException(status_code=404, detail=f"Squad com ID {squad_id} não encontrado.")
    return None # Retorna 204 No Content

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