from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "database.db"
DEFAULT_SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
SQLALCHEMY_DATABASE_URL = settings.database_url or DEFAULT_SQLALCHEMY_DATABASE_URL

is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}

# Pool dimensionado para múltiplos workers do Uvicorn com Postgres.
# Cada worker do Uvicorn cria seu próprio engine+pool, então o total
# de conexões simultâneas em pico é: workers × (pool_size + max_overflow).
# Com 4 workers e os valores abaixo ficamos em ~100 conexões máximas.
# Ajuste max_connections do Postgres no docker-compose.yml acompanhando.
engine_kwargs: dict = {"connect_args": connect_args}
if not is_sqlite:
    engine_kwargs.update(
        pool_size=15,
        max_overflow=10,
        pool_pre_ping=True,   # evita erro "server closed the connection unexpectedly"
        pool_recycle=1800,    # recicla conexões a cada 30min
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
