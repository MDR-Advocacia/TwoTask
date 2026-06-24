"""OneRequest: cache do status da tarefa no Legal One por DMI

Revision ID: onr003_l1_status_cache
Revises: pin025
Create Date: 2026-06-24

Acompanhamento sob demanda (botão "Atualizar status L1" na UI): grava, por DMI,
o resultado da checagem no Legal One —
  - l1_checked_at      : quando foi a última checagem;
  - l1_dmi_task_id     : id da tarefa da DMI achada na pasta (match por número
                         da solicitação na descrição); None = não encontrada;
  - l1_dmi_status_id   : status dessa tarefa (0 Pendente, 1 Cumprido, 2 Não
                         cumprido, 3 Cancelado, 4 Iniciado, 5 Reagendado);
  - l1_pendentes_count : nº de tarefas Pendente/Iniciado na pasta (0 = sem
                         pendência).
Tudo nullable: linha sem checagem fica vazia. Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "onr003_l1_status_cache"
down_revision = "pin025"
branch_labels = None
depends_on = None


_COLS = (
    ("l1_checked_at", lambda: sa.Column("l1_checked_at", sa.DateTime(timezone=True), nullable=True)),
    ("l1_dmi_task_id", lambda: sa.Column("l1_dmi_task_id", sa.Integer(), nullable=True)),
    ("l1_dmi_status_id", lambda: sa.Column("l1_dmi_status_id", sa.Integer(), nullable=True)),
    ("l1_pendentes_count", lambda: sa.Column("l1_pendentes_count", sa.Integer(), nullable=True)),
)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    for name, maker in _COLS:
        if not _has_column("onr_solicitacoes", name):
            op.add_column("onr_solicitacoes", maker())


def downgrade() -> None:
    for name, _ in reversed(_COLS):
        if _has_column("onr_solicitacoes", name):
            op.drop_column("onr_solicitacoes", name)
