# CONTEÚDO FINAL E CORRIGIDO para: main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import admin, dashboard, tasks

app = FastAPI(title="OneTask API", version="1.0.0")

# Configuração do CORS para permitir a comunicação com o frontend React
origins = [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Roteadores da API
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])

# Endpoint Raiz
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Bem-vindo à API OneTask"}