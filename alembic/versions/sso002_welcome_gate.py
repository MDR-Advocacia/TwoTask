"""SSO welcome gate: last_sso_at + publicações sem permissão por default

- Adiciona last_sso_at (carimbo do login via Entra) — selo "Entra ID" no admin.
- Muda o default de can_use_publications pra FALSE: novos acessos entram SEM
  permissão de nada (o admin libera). Antes o default era True e todo usuário
  novo já via o módulo de Publicações.
- Backfill: zera can_use_publications de quem NUNCA usou o Flow (sem senha) —
  esses caem na tela de boas-vindas no 1º acesso SSO. Quem já trabalha no Flow
  (tem senha) mantém o acesso intacto.

Revision ID: sso002
Revises: con001
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "sso002"
down_revision: Union[str, None] = "con001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "legal_one_users",
        sa.Column("last_sso_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "legal_one_users",
        "can_use_publications",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )
    # Zera publicações de quem nunca ativou o Flow (sem senha) — entram sem
    # permissão e veem a tela de boas-vindas. Estabelecidos (com senha) mantêm.
    op.execute(
        "UPDATE legal_one_users SET can_use_publications = false "
        "WHERE hashed_password IS NULL"
    )


def downgrade() -> None:
    op.alter_column(
        "legal_one_users",
        "can_use_publications",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
    )
    op.drop_column("legal_one_users", "last_sso_at")
