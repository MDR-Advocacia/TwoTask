# app/main.py

from fastapi import FastAPI # type: ignore
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import admin, dashboard, tasks

app = FastAPI(title="OneTask API", version="1.0.0")

# Configuração do CORS
origins = [
    "http://localhost:5173",
    "http://localhost:8080",   # Adicionando a porta do vite.config.ts
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Roteadores da API (Como estavam antes)
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(
    dashboard.router,
    prefix="/api/v1/dashboard",
    tags=["Dashboard"]
)
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])


# Endpoint Raiz
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Bem-vindo à API OneTask"}
