# file: main.py

from fastapi import FastAPI
from app.api.v1.endpoints import tasks as tasks_v1
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente de um arquivo .env (ótimo para desenvolvimento local)
load_dotenv()

# Cria a instância principal da aplicação FastAPI
app = FastAPI(
    title="Legal One Integration Service",
    description="Serviço para automatizar a criação de tarefas no Legal One.",
    version="1.0.0"
)

# Inclui o roteador com os endpoints de tarefas sob o prefixo /api/v1
app.include_router(tasks_v1.router, prefix="/api/v1")

@app.get("/", tags=["Health Check"])
def read_root():
    """Endpoint raiz para verificação de saúde (health check)."""
    return {"status": "ok", "service": "Legal One Integration Service"}