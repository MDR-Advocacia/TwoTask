"""add natureza_processo + produto to prazo_inicial_intakes

Fase 3c — `natureza_processo` é o router do prompt (COMUM/JUIZADO/
AGRAVO_INSTRUMENTO/OUTRO). `produto` é informativo apenas (SUPERENDIVIDA-
MENTO/CREDCESTA/...). Ambos são VARCHAR NULL — intakes anteriores à
Fase 3c ficam com NULL e serão preenchidos sob demanda pela HITL ou na
próxima reclassificação.

Revision ID: pin003
Revises: pin002
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "pin003"
down_revision = "pin002"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("prazo_inicial_intakes", "natureza_processo"):
        op.add_column(
            "prazo_inicial_intakes",
            sa.Column("natureza_processo", sa.String(length=64), nullable=True),
        )
    if not _has_column("prazo_inicial_intakes", "produto"):
        op.add_column(
            "prazo_inicial_intakes",
            sa.Column("produto", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    if _has_column("prazo_inicial_intakes", "produto"):
        op.drop_column("prazo_inicial_intakes", "produto")
    if _has_column("prazo_inicial_intakes", "natureza_processo"):
        op.drop_column("prazo_inicial_intakes", "natureza_processo")
