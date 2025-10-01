from fastapi import APIRouter
from typing import List

router = APIRouter()

# In a real application, this would be a more complex model.
# For now, an empty list is sufficient to prevent the frontend from crashing.
@router.get("/task_templates", response_model=List, summary="Listar todos os templates de tarefa", tags=["Task Templates"])
def get_all_task_templates():
    """
    Retorna uma lista de templates de tarefa.
    Atualmente retorna uma lista vazia para fins de estabilidade.
    """
    return []