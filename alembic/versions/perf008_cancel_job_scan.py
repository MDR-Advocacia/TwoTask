"""Performance: fase de varredura LIVE no job de cancelamento de duplicadas

Revision ID: perf008_cancel_job_scan
Revises: perf007_cancel_job
Create Date: 2026-06-30

O cancelamento de duplicadas passa a varrer o L1 AO VIVO antes de cancelar
(acha as duplicadas reais de agora, não as do snapshot). Adiciona fase +
progresso da varredura ao job. Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "perf008_cancel_job_scan"
down_revision = "perf007_cancel_job"
branch_labels = None
depends_on = None


def _cols(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _cols("perf_cancel_job")
    if not cols:
        return
    if "fase" not in cols:
        op.add_column("perf_cancel_job", sa.Column("fase", sa.String(), nullable=False, server_default="scanning"))
    if "scan_total" not in cols:
        op.add_column("perf_cancel_job", sa.Column("scan_total", sa.Integer(), nullable=False, server_default="0"))
    if "scan_feito" not in cols:
        op.add_column("perf_cancel_job", sa.Column("scan_feito", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    cols = _cols("perf_cancel_job")
    for c in ("scan_feito", "scan_total", "fase"):
        if c in cols:
            op.drop_column("perf_cancel_job", c)
