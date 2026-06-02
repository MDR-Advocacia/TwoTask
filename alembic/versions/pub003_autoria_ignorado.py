"""adiciona ignored_by (quem deu ciência/ignorou) em publicacao_registros

Colunas novas:
- ignored_by_user_id: FK opcional pro LegalOneUser (rastreio do usuário logado)
- ignored_by_email:   snapshot do email (independe se o user for deletado)
- ignored_by_name:    snapshot do nome legível
- ignored_at:         carimbo da hora em que deu ciência

Espelha exatamente o padrão de scheduled_by (migration pub002). Preenchido
pelo endpoint PATCH /records/{id} no momento em que o operador move o
registro pra status=IGNORADO ("dar ciência"). Junto com scheduled_by, fecha
a autoria das DUAS ações humanas de tratamento (agendar + dar ciência) — a
transição NOVO→CLASSIFICADO é automática (IA), por isso não tem autoria.

Serve pra exibir "Ciência dada por X" e pra compor o placar individual de
tratamento (gamificação). Registros pré-migration ficam NULL — sem backfill.

Revision ID: pub003
Revises: var001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pub003"
down_revision: Union[str, None] = "var001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "publicacao_registros",
        sa.Column("ignored_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "publicacao_registros",
        sa.Column("ignored_by_email", sa.String(), nullable=True),
    )
    op.add_column(
        "publicacao_registros",
        sa.Column("ignored_by_name", sa.String(), nullable=True),
    )
    op.add_column(
        "publicacao_registros",
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
    )
    # FK pro LegalOneUser — ON DELETE SET NULL pra não bloquear remoção de
    # usuário e preservar o histórico via email/name snapshot.
    op.create_foreign_key(
        "fk_publicacao_registros_ignored_by_user",
        "publicacao_registros",
        "legal_one_users",
        ["ignored_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Índice leve pra consultas "quem deu ciência" e agregação por usuário.
    op.create_index(
        "ix_publicacao_registros_ignored_by_user_id",
        "publicacao_registros",
        ["ignored_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publicacao_registros_ignored_by_user_id",
        table_name="publicacao_registros",
    )
    op.drop_constraint(
        "fk_publicacao_registros_ignored_by_user",
        "publicacao_registros",
        type_="foreignkey",
    )
    op.drop_column("publicacao_registros", "ignored_at")
    op.drop_column("publicacao_registros", "ignored_by_name")
    op.drop_column("publicacao_registros", "ignored_by_email")
    op.drop_column("publicacao_registros", "ignored_by_user_id")
