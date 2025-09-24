from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.models.rules import Squad
from app.models.legal_one import LegalOneUser

router = APIRouter()

# O Jinja2Templates agora procura os templates na pasta 'templates'
templates = Jinja2Templates(directory="templates")

# Nova rota para a landing page do dashboard
@router.get("/", response_class=HTMLResponse)
async def get_dashboard_landing(request: Request):
    """
    Exibe a landing page principal do dashboard com os cartões de navegação.
    """
    context = {
        "request": request,
        "page_title": "Dashboard Principal"
    }
    return templates.TemplateResponse("dashboard.html", context)

# Rota ajustada para a página de gerenciamento de squads
@router.get("/squads", response_class=HTMLResponse)
async def get_squad_management_page(request: Request, db: Session = Depends(get_db)):
    """
    Exibe a página de gerenciamento de squads.
    """
    squads = db.query(Squad).order_by(Squad.name).all()
    legal_one_users = db.query(LegalOneUser).order_by(LegalOneUser.name).all()
    
    context = {
        "request": request,
        "squads": squads,
        "legal_one_users": legal_one_users,
        "page_title": "Gerenciamento de Squads"
    }
    return templates.TemplateResponse("squads.html", context)