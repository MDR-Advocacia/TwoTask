"""Performance: whitelist + auditoria do cancelamento de duplicadas EM MASSA

Revision ID: perf009_cancel_massa
Revises: perf008_cancel_job_scan
Create Date: 2026-06-30

Rotina noturna que cancela duplicadas (mesma pasta+subtipo) das carteiras sobre
o pool fresco. Só atua nos subtipos da whitelist (incrementável pela UI) — começa
com 'Agendar Prazos - Banco Master'. Cada execução grava auditoria total.
Idempotente.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "perf009_cancel_massa"
down_revision = "perf008_cancel_job_scan"
branch_labels = None
depends_on = None

_SEED_SUBTIPO = "Agendar Prazos - Banco Master"


def _has_table(t: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(t)


def upgrade() -> None:
    if not _has_table("perf_cancel_whitelist"):
        op.create_table(
            "perf_cancel_whitelist",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("subtipo", sa.String(), nullable=False, unique=True),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("criado_por", sa.String(), nullable=True),
        )
        # Semeia com o desvio de fluxo conhecido.
        op.execute(
            sa.text(
                "INSERT INTO perf_cancel_whitelist (subtipo, ativo, criado_por) "
                "VALUES (:s, true, 'seed') ON CONFLICT (subtipo) DO NOTHING"
            ).bindparams(s=_SEED_SUBTIPO)
        )

    if not _has_table("perf_cancel_massa_log"):
        op.create_table(
            "perf_cancel_massa_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("iniciado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("terminado_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="running"),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("origem", sa.String(), nullable=True),
            sa.Column("total_candidatos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cancelled", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("preservadas", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("falhas", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("detalhe", JSONB(), nullable=True),
        )


def downgrade() -> None:
    for t in ("perf_cancel_massa_log", "perf_cancel_whitelist"):
        if _has_table(t):
            op.drop_table(t)
