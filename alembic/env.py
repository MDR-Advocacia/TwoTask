# Arquivo: alembic/env.py

# ==============================================================================
# PASSO 1: CONFIGURAR O CAMINHO DO PYTHON PARA ENCONTRAR NOSSO CÓDIGO
# Este bloco é a correção para o erro "ModuleNotFoundError: No module named 'app'".
# Ele adiciona a pasta raiz do nosso projeto (onetask) ao caminho onde o
# Python procura por módulos, permitindo que a importação 'from app...' funcione.
# ==============================================================================
import sys
from os.path import abspath, dirname

sys.path.insert(0, dirname(dirname(abspath(__file__))))

# ==============================================================================
# IMPORTS PADRÃO E DOS NOSSOS MODELOS
# ==============================================================================
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# ==============================================================================
# PASSO 2: IMPORTAR NOSSA "BASE" DECLARATIVA DO SQLALCHEMY
# Esta linha importa a 'Base' que declaramos no arquivo de modelos. É a partir
# dela que o Alembic descobre quais tabelas nós definimos em nosso código.
# ==============================================================================
from app.models.rules import Base

# esta é a variável de configuração do Alembic que lê o arquivo alembic.ini
config = context.config

# Interpreta o arquivo de configuração para o logging do Python.
# Esta linha basicamente configura os loggers.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ==============================================================================
# PASSO 3: DEFINIR O METADATA PARA O AUTOGENERATE
# Esta é a parte mais importante para o '--autogenerate' funcionar.
# Nós dizemos ao Alembic: "As tabelas que você deve procurar estão
# definidas no metadata da nossa Base".
# ==============================================================================
target_metadata = Base.metadata

# outras opções podem ser passadas aqui do arquivo .ini, por exemplo:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Executa as migrações no modo 'offline'.
    Este modo gera scripts SQL a partir de um banco de dados offline.
    """
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
    """Executa as migrações no modo 'online'.
    Neste modo, nós nos conectamos ao banco de dados e geramos os comandos DDL
    diretamente. É o modo que usamos na prática.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()