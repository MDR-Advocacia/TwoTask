"""Cria tabela app_settings (key/value) e seedeia o toggle taxonomy_active_version='v1'.

Tabela de chave-valor pra settings globais da aplicacao. Foi pensada
inicialmente pra o toggle taxonomy v1<->v2 (fase 11), mas e generica
o suficiente pra acomodar outros switches admin no futuro.

Schema simples: key (PK string), value (text), description (text),
updated_at (timestamp). Sem audit log — o caller pode logar via
logger.info quando muda valor critico.

Seed inicial:
  - "taxonomy_active_version" = "v1" (preserva comportamento atual)

Revision ID: tax008
Revises: tax007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax008"
down_revision: Union[str, None] = "tax007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CREATE TABLE idempotente via raw SQL pra alinhar com o estilo
    # das outras migrations da casa (ALTER TABLE IF NOT EXISTS).
    op.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key varchar(64) PRIMARY KEY,
            value text NOT NULL,
            description text,
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
    """)

    # Seed do toggle inicial. ON CONFLICT DO NOTHING garante que rerun
    # da migration nao sobrescreve um valor que o operador ja mudou
    # (ex.: virou pra 'v2' depois de revisar todos os pendentes).
    op.execute("""
        INSERT INTO app_settings (key, value, description)
        VALUES (
            'taxonomy_active_version',
            'v1',
            'Versao da taxonomia ativa globalmente. v1=legacy, v2=nova com polos. Mude via Admin > Toggle Taxonomy quando todos os templates pendentes forem revisados.'
        )
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings")
