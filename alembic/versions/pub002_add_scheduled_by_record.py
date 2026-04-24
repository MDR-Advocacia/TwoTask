"""adiciona scheduled_by (quem agendou) em publicacao_registros

Colunas novas:
- scheduled_by_user_id: FK opcional pro LegalOneUser (rastreio do usuário logado)
- scheduled_by_email:   snapshot do email (independe se o user for deletado)
- scheduled_by_name:    snapshot do nome legível
- scheduled_at:         carimbo da hora do agendamento

Preenchido pelos endpoints de agendar no momento em que o registro muda pra
status=AGENDADO. Serve pra exibir "Agendado por X" na listagem e compor a
trilha de auditoria do processo.

Revision ID: pub002
Revises: pin010
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pub002"
down_revision: Union[str, None] = "pin010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "publicacao_registros",
        sa.Column("scheduled_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "publicacao_registros",
        sa.Column("scheduled_by_email", sa.String(), nullable=True),
    )
    op.add_column(
        "publicacao_registros",
        sa.Column("scheduled_by_name", sa.String(), nullable=True),
    )
    op.add_column(
        "publicacao_registros",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # FK pro LegalOneUser — ON DELETE SET NULL pra não bloquear remoção de
    # usuário e preservar o histórico via email/name snapshot.
    op.create_foreign_key(
        "fk_publicacao_registros_scheduled_by_user",
        "publicacao_registros",
        "legal_one_users",
        ["scheduled_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Índice leve pra consultas "quem agendou isso" e filtros por usuário.
    op.create_index(
        "ix_publicacao_registros_scheduled_by_user_id",
        "publicacao_registros",
        ["scheduled_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publicacao_registros_scheduled_by_user_id",
        table_name="publicacao_registros",
    )
    op.drop_constraint(
        "fk_publicacao_registros_scheduled_by_user",
        "publicacao_registros",
        type_="foreignkey",
    )
    op.drop_column("publicacao_registros", "scheduled_at")
    op.drop_column("publicacao_registros", "scheduled_by_name")
    op.drop_column("publicacao_registros", "scheduled_by_email")
    op.drop_column("publicacao_registros", "scheduled_by_user_id")
