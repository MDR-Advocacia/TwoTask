# Conteúdo final e corrigido para: alembic/env.py

from pathlib import Path
import sys

# --- INÍCIO DA CORREÇÃO (Sugerida por você) ---
# Adiciona a raiz do projeto ao PYTHONPATH de forma robusta
sys.path.append(str(Path(__file__).resolve().parents[1]))
# --- FIM DA CORREÇÃO ---

from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Importa a Base do seu core e TODOS os modelos para que o autogenerate os detecte.
from app.db.session import Base
from app.models.canonical import *
from app.models.legal_one import *
from app.models.rules import *
from app.models.associations import *
from app.models.task_group import *

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Define o target_metadata para o autogenerate
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), # Já corrigido
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True  # <-- ADICIONE ESTA LINHA
        )

        with context.begin_transaction():
            context.run_migrations()
            
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()