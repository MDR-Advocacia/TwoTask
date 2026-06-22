"""arquivamento em lote de intakes (soft-delete) — colunas archived_*

Revision ID: pin025
Revises: ajus010
Create Date: 2026-06-22

Adiciona ao prazo_inicial_intakes as colunas de arquivamento em lote
(soft-delete de entradas antigas/irrelevantes):
- archived_at (indexada) / archived_by_user_id / archived_by_email /
  archived_by_name.

O status novo "ARQUIVADO" é texto livre no campo `status` (sem enum no DB),
então não precisa de schema. A listagem ativa esconde ARQUIVADO por padrão;
o status anterior é preservado em metadata_json para eventual restauração.
Todas as colunas nullable — intakes antigos ficam com archived_at NULL
(= não arquivados).
"""
from alembic import op
import sqlalchemy as sa

revision = "pin025"
down_revision = "ajus010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("archived_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("archived_by_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("archived_by_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_prazo_inicial_intakes_archived_at",
        "prazo_inicial_intakes",
        ["archived_at"],
    )


def downgrade():
    op.drop_index(
        "ix_prazo_inicial_intakes_archived_at",
        table_name="prazo_inicial_intakes",
    )
    for col in (
        "archived_by_name",
        "archived_by_email",
        "archived_by_user_id",
        "archived_at",
    ):
        op.drop_column("prazo_inicial_intakes", col)
