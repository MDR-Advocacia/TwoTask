# app/api/v1/endpoints/dashboard.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.core.dependencies import get_db
# Importar os modelos de 'rules' e 'canonical'
from app.models import canonical as canonical_models
from app.models import rules as rules_models # <--- MUDANÇA IMPORTANTE
from app.api.v1 import schemas

router = APIRouter()

@router.get("/task_templates", response_model=List[schemas.TaskTemplate])
def get_task_templates(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os templates de tarefas canônicos.
    (Este endpoint continua o mesmo, pois lê de 'canonical')
    """
    templates = db.query(canonical_models.CanonicalTaskTemplate).all()
    if not templates:
        raise HTTPException(status_code=404, detail="Nenhum template de tarefa encontrado.")
    return templates

# --- CORREÇÃO APLICADA AQUI ---
@router.get("/squads", response_model=List[schemas.Squad])
def get_squads(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os squads e membros ATIVOS a partir dos
    dados sincronizados (tabelas de 'rules').
    """
    # A consulta agora é feita nos modelos 'rules_models'
    # e filtra para trazer apenas os registros ativos.
    squads = (
        db.query(rules_models.Squad)
        .filter(rules_models.Squad.is_active == True) # <--- Garante que apenas squads ativos sejam retornados
        .options(
            joinedload(rules_models.Squad.members)
        )
        .all()
    )
    
    if not squads:
        raise HTTPException(status_code=404, detail="Nenhum squad ativo encontrado.")
        
    # Precisamos filtrar os membros inativos manualmente se o relacionamento não o fizer
    active_squads = []
    for squad in squads:
        # Cria um novo objeto Squad para a resposta, contendo apenas membros ativos
        squad_data = schemas.Squad.from_orm(squad)
        squad_data.members = [member for member in squad.members if member.is_active]
        active_squads.append(squad_data)

    return active_squads