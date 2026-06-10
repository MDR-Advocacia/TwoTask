"""make legal_one_users.external_id nullable (SSO/Entra JIT users)

Usuários provisionados via SSO (Microsoft Entra ID) ainda não existem no
Legal One no primeiro acesso, então não têm external_id. Esta migration
torna a coluna opcional. Usuários sincronizados do Legal One continuam com
seu external_id normalmente. O índice único é mantido — no Postgres, NULLs
são distintos entre si, então múltiplos usuários SSO sem external_id são OK.

Revision ID: sso001
Revises: tax015
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "sso001"
down_revision: Union[str, None] = "tax015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensões pra busca de similaridade de nome (vínculo SSO ↔ Legal One),
    # usadas no /admin/sso/pending. Idempotente.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.alter_column(
        "legal_one_users",
        "external_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Atenção: se existirem usuários SSO com external_id NULL, este downgrade
    # falha (NOT NULL violado). Limpe/preencha antes de reverter.
    op.alter_column(
        "legal_one_users",
        "external_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
