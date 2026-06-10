"""Aplica migrations no boot do container (chamado pelo docker-api-start.sh).

GUARDA DE SEGURANÇA: se o banco estiver VAZIO (sem alembic_version populada),
o script ABORTA em vez de inicializar do zero. Em produção, banco vazio
significa volume errado/desanexado — subir nesse estado colocaria uma base
zerada no ar. Pra inicializar um ambiente NOVO de propósito (lab, dev),
defina ALLOW_DB_BOOTSTRAP=true no ambiente.

Histórico: a versão antiga deste script era para SQLite e imprimia
"Database does not exist, will be created by migrations" em todo deploy
com Postgres (o os.path.exists numa URL postgres é sempre False) — um
alarme falso que causou pânico no incidente de 2026-06-10.
"""
import os
import sys
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.session import SQLALCHEMY_DATABASE_URL

ALLOW_DB_BOOTSTRAP = os.getenv("ALLOW_DB_BOOTSTRAP", "").strip().lower() in (
    "1", "true", "yes", "on",
)

CONNECT_RETRIES = 15
CONNECT_RETRY_DELAY_S = 2


def get_current_version() -> "str | None":
    """Retorna o version_num do alembic_version, ou None se banco virgem.

    Tenta conectar com retry (o Postgres pode estar terminando de subir,
    mesmo com depends_on: service_healthy)."""
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
    last_exc: "Exception | None" = None
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            with engine.connect() as conn:
                if not inspect(conn).has_table("alembic_version"):
                    return None
                return conn.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar()
        except Exception as exc:  # conexão recusada, DNS, banco subindo...
            last_exc = exc
            print(
                f"Banco indisponível (tentativa {attempt}/{CONNECT_RETRIES}): {exc}"
            )
            time.sleep(CONNECT_RETRY_DELAY_S)
    print(f"ERRO: não foi possível conectar ao banco: {last_exc}")
    sys.exit(1)


def main() -> None:
    version = get_current_version()

    if version is None:
        if not ALLOW_DB_BOOTSTRAP:
            print("=" * 72)
            print("ABORTADO: banco de dados VAZIO detectado (sem alembic_version).")
            print("Em produção isso indica volume errado ou desanexado — prosseguir")
            print("criaria uma base ZERADA no ar. Verifique o mapeamento de volume")
            print("do Postgres (Coolify > serviço postgres > Storages).")
            print("Se isto é um ambiente NOVO de propósito (lab/dev), defina a env")
            print("ALLOW_DB_BOOTSTRAP=true e rode o deploy novamente.")
            print("=" * 72)
            sys.exit(1)
        print("ALLOW_DB_BOOTSTRAP=true — inicializando banco NOVO do zero.")
    else:
        print(f"Banco existente (alembic_version={version}). Aplicando migrations pendentes...")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)
    command.upgrade(config, "head")
    print("Migrations aplicadas com sucesso.")


if __name__ == "__main__":
    main()
