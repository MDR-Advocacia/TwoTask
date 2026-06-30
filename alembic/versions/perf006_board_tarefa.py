"""Performance: curadoria do board 'Tarefas mais importantes' por time

Revision ID: perf006_board_tarefa
Revises: bal002_fila_pref
Create Date: 2026-06-30

Quando um time tem linhas em perf_board_tarefa, o board mostra exatamente esses
subtipos (na ordem). Sem linhas, mantém o default top-N por volume. Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "perf006_board_tarefa"
down_revision = "bal002_fila_pref"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("perf_board_tarefa"):
        return
    op.create_table(
        "perf_board_tarefa",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team", sa.String(), nullable=False, index=True),
        sa.Column("subtipo", sa.String(), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("team", "subtipo", name="uq_board_tarefa"),
    )


def downgrade() -> None:
    if _has_table("perf_board_tarefa"):
        op.drop_table("perf_board_tarefa")
