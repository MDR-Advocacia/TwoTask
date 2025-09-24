# Conteúdo ATUALIZADO para: main.py

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware  # Importe o Middleware
from app.api.v1.endpoints import admin, dashboard, tasks

# Cria a instância principal da aplicação FastAPI
app = FastAPI(title="OneTask API", version="1.0.0")

# --- ADIÇÃO CRUCIAL: Configuração do CORS ---
# Permite que o frontend React (rodando em http://localhost:5173)
# faça requisições para esta API.
origins = [
    "http://localhost:5173",
    "http://localhost:3000", # Adicione outras portas se necessário
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Permite todos os métodos (GET, POST, etc)
    allow_headers=["*"], # Permite todos os cabeçalhos
)
# --- FIM DA CONFIGURAÇÃO DO CORS ---


# Monta o diretório 'static' - Isso não é mais necessário para o React, mas podemos manter por enquanto.
app.mount("/static", StaticFiles(directory="static"), name="static")

# Inclui os roteadores dos diferentes módulos da sua aplicação
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])

# Adiciona um endpoint raiz para verificação de saúde da API
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Bem-vindo à API OneTask"}