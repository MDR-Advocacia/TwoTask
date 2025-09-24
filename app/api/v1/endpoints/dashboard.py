# app/api/v1/endpoints/dashboard.py

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_db
from app.models.rules import Squad, SquadMember # SquadMember é novo aqui
from app.models.legal_one import LegalOneUser

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def read_dashboard(request: Request, db: Session = Depends(get_db)):
    """
    Renderiza a página principal do dashboard.
    """
    return templates.TemplateResponse("dashboard.html", {"request": request, "page_title": "Dashboard Principal"})

# --- NOVO ENDPOINT ADICIONADO AQUI ---
@router.get("/squad-management", response_class=HTMLResponse, summary="Página de Gestão de Squads")
async def get_squad_management_page(request: Request, db: Session = Depends(get_db)):
    """
    Busca os dados necessários e renderiza a página de gerenciamento
    e associação de membros de squad com usuários do Legal One.
    """
    # 1. Busca squads com seus membros e o usuário L1 já vinculados (para evitar múltiplas queries)
    squads = db.query(Squad).options(
        joinedload(Squad.members).joinedload(SquadMember.legal_one_user)
    ).filter(Squad.is_active == True).order_by(Squad.name).all()

    # 2. Busca todos os usuários ativos do Legal One para popular os dropdowns
    legal_one_users = db.query(LegalOneUser).filter(LegalOneUser.is_active == True).order_by(LegalOneUser.name).all()

    # 3. Prepara o contexto para o template
    context = {
        "request": request,
        "page_title": "Gestão de Squads e Usuários",
        "squads": squads,
        "legal_one_users_options": legal_one_users
    }
    
    # 4. Renderiza o novo template que vamos criar
    return templates.TemplateResponse("squad_management.html", context)