# app/api/v1/endpoints/dashboard.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.core.dependencies import get_db
# Importar os modelos existentes
from app.models import canonical as canonical_models
from app.models import rules as rules_models
# Adicionar import do novo modelo de log
from app.models.batch_execution import BatchExecution
from app.api.v1 import schemas

router = APIRouter()

# --- SEUS ENDPOINTS EXISTENTES (INALTERADOS) ---

@router.get("/task_templates", response_model=List[schemas.TaskTemplate])
def get_task_templates(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os templates de tarefas canônicos.
    """
    templates = db.query(canonical_models.CanonicalTaskTemplate).all()
    if not templates:
        raise HTTPException(status_code=404, detail="Nenhum template de tarefa encontrado.")
    return templates

@router.get("/squads", response_model=List[schemas.Squad])
def get_squads(db: Session = Depends(get_db)):
    """
    Endpoint para buscar todos os squads e membros ATIVOS a partir dos
    dados sincronizados (tabelas de 'rules').
    """
    squads = (
        db.query(rules_models.Squad)
        .filter(rules_models.Squad.is_active == True)
        .options(
            joinedload(rules_models.Squad.members)
        )
        .all()
    )
    
    if not squads:
        raise HTTPException(status_code=404, detail="Nenhum squad ativo encontrado.")
        
    active_squads = []
    for squad in squads:
        squad_data = schemas.Squad.from_orm(squad)
        # Filtra manualmente para garantir que apenas membros ativos sejam incluídos
        squad_data.members = [member for member in squad.members if hasattr(member, 'is_active') and member.is_active]
        active_squads.append(squad_data)

    return active_squads

# --- NOSSO NOVO ENDPOINT ADICIONADO AQUI ---

@router.get(
    "/batch-executions",
    response_model=List[schemas.BatchExecutionResponse],
    summary="Obtém o histórico das últimas execuções de tarefas em lote"
)
def get_batch_executions(
    db: Session = Depends(get_db),
    limit: int = 20
):
    """
    Retorna uma lista das últimas N execuções de lote processadas pela API,
    com os detalhes de cada item (sucesso ou falha).
    
    - **limit**: Número de execuções a serem retornadas (padrão: 20).
    """
    executions = (
        db.query(BatchExecution)
        .options(joinedload(BatchExecution.items)) # Otimiza a query para carregar os itens juntos
        .order_by(BatchExecution.start_time.desc())
        .limit(limit)
        .all()
    )
    return executions