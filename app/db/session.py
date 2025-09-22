# Salvar como: app/db/session.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Define o caminho para o arquivo do banco de dados SQLite
SQLALCHEMY_DATABASE_URL = "sqlite:///../database.db"

# Cria o motor de conexão do SQLAlchemy
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Cria uma classe de sessão que será usada para interagir com o banco
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- A LINHA MAIS IMPORTANTE ---
# Cria a classe Base da qual todos os seus modelos de banco de dados devem herdar.
Base = declarative_base()