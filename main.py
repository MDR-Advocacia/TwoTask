from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.v1.endpoints import admin, dashboard, tasks

# Cria a instância principal da aplicação FastAPI
app = FastAPI(title="OneTask API", version="1.0.0")

# Monta o diretório 'static' para servir arquivos estáticos como CSS e JS
app.mount("/static", StaticFiles(directory="static"), name="static")

# Inclui os roteadores dos diferentes módulos da sua aplicação
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])

# Adiciona um endpoint raiz para verificação de saúde da API
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Bem-vindo à API OneTask"}