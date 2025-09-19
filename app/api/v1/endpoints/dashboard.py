# file: app/api/v1/endpoints/dashboard.py

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.squad_manager import get_squad_manager, SquadManager

router = APIRouter()

# Garanta que você tem uma pasta 'templates' na raiz do projeto
templates = Jinja2Templates(directory="templates")

@router.get("/dashboard", response_class=HTMLResponse, tags=["Painel de Controle"])
async def read_dashboard(request: Request):
    """
    Renderiza a página principal do painel de controle.
    """
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/api/v1/squads", response_class=JSONResponse, tags=["Painel de Controle"])
def get_squads_data(squad_manager: SquadManager = Depends(get_squad_manager)):
    """
    Endpoint de API para o frontend buscar os dados das squads.
    """
    config = squad_manager.get_config()
    if "error" in config:
        return JSONResponse(status_code=500, content=config)
    return JSONResponse(status_code=200, content=config)