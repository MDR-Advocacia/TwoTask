# file: main.py

import os
from dotenv import load_dotenv

# AÇÃO CRÍTICA: Carrega as variáveis de ambiente ANTES de qualquer importação da app.
# Isso garante que todas as variáveis estejam disponíveis quando os outros módulos forem lidos.
load_dotenv()

from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from app.api.v1.endpoints import tasks as tasks_v1
from app.api.v1.endpoints import dashboard as dashboard_v1
from app.core.squad_manager import get_squad_manager, SquadManager

app = FastAPI(
    title="Legal One Integration Service",
    description="Serviço para automatizar a criação de tarefas e gerenciar fluxos.",
    version="1.1.0"
)

# Inclui os roteadores da aplicação
app.include_router(tasks_v1.router, prefix="/api/v1")
app.include_router(dashboard_v1.router)

@app.get("/", tags=["Health Check"])
def read_root():
    """Endpoint raiz para verificação de saúde (health check)."""
    return {"status": "ok", "service": "Legal One Integration Service"}

@app.post("/api/v1/admin/refresh-squads", tags=["Admin"])
def refresh_squads_cache(squad_manager: SquadManager = Depends(get_squad_manager)):
    """
    Força a recarga dos dados das squads a partir da API interna.
    """
    result = squad_manager.force_refresh()
    if result.get("status") == "error":
        return JSONResponse(status_code=500, content={"success": False, "detail": result.get("message")})
    return JSONResponse(status_code=200, content={"success": True, "detail": "Cache de SQUADS atualizado com sucesso."})