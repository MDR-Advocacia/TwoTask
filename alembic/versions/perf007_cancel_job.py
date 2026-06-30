"""Performance: job persistido de cancelamento em lote de duplicadas (fase B)

Revision ID: perf007_cancel_job
Revises: perf006_board_tarefa
Create Date: 2026-06-30

Status do lote de cancelamento de duplicadas persistido em tabela pra o polling
funcionar com múltiplos workers do uvicorn. Idempotente.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "perf007_cancel_job"
down_revision = "perf006_board_tarefa"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("perf_cancel_job"):
        return
    op.create_table(
        "perf_cancel_job",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("team", sa.String(), nullable=True),
        sa.Column("subtipo", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("feito", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("preservadas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("falhas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("erros", JSONB(), nullable=True),
        sa.Column("iniciado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("terminado_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if _has_table("perf_cancel_job"):
        op.drop_table("perf_cancel_job")
