"""OneRequest: verificação proativa de existência do processo no Legal One

Revision ID: onr004_proc_l1_check
Revises: onr003_l1_status_cache
Create Date: 2026-06-25

Resolve o processo (CNJ -> NPJ) SEM criar tarefa, só pra sinalizar no painel se
a pasta existe no L1 ANTES do agendamento (o operador descobre cedo que o caso
precisa de tratamento especial — ex.: viabilidade de ajuizamento, processo
baixado no cliente, número que nunca virou pasta aqui):
  - proc_l1_checado_em : quando rodou a verificação (None = nunca checado);
  - proc_l1_encontrado : True = pasta achada no L1; False = checado e não achada;
  - proc_l1_via        : como achou ("cnj" / "npj" / "cache"); None se não achou.
Tudo nullable. Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "onr004_proc_l1_check"
down_revision = "onr003_l1_status_cache"
branch_labels = None
depends_on = None


_COLS = (
    ("proc_l1_checado_em", lambda: sa.Column("proc_l1_checado_em", sa.DateTime(timezone=True), nullable=True)),
    ("proc_l1_encontrado", lambda: sa.Column("proc_l1_encontrado", sa.Boolean(), nullable=True)),
    ("proc_l1_via", lambda: sa.Column("proc_l1_via", sa.String(), nullable=True)),
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
