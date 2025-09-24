# Conteúdo completo e corrigido para: app/db/session.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from pathlib import Path

# --- INÍCIO DA CORREÇÃO ---
# Constrói o caminho absoluto para o arquivo do banco de dados na raiz do projeto.
# Path(__file__) -> /caminho/completo/para/o/projeto/app/db/session.py
# .parent -> app/db
# .parent -> app
# .parent -> raiz do projeto
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
# --- FIM DA CORREÇÃO ---

# Cria o motor de conexão do SQLAlchemy
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Cria uma classe de sessão que será usada para interagir com o banco
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Cria a classe Base da qual todos os seus modelos de banco de dados devem herdar.
Base = declarative_base()

# --- INÍCIO DA ADIÇÃO ---
def get_db():
    """
    Função de dependência do FastAPI para obter uma sessão do banco de dados.
    Garante que a sessão seja sempre fechada após a requisição.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
# --- FIM DA ADIÇÃO ---