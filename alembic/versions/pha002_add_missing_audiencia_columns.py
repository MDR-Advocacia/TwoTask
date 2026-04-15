"""add missing audiencia/classifications columns to publicacao_registros

Revision ID: pha002
Revises: pha001
Create Date: 2026-04-14

Corrige drift entre o modelo SQLAlchemy e a tabela no Postgres:
as colunas audiencia_data, audiencia_hora, audiencia_link e classifications
existem no modelo mas não foram criadas no Postgres durante a migração
SQLite → Postgres.
"""
from alembic import op
import sqlalchemy as sa


revision = "pha002"
down_revision = "pha001"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    res = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return bool(res)


def upgrade() -> None:
    table = "publicacao_registros"

    if not _has_column(table, "audiencia_data"):
        op.add_column(table, sa.Column("audiencia_data", sa.String(), nullable=True))

    if not _has_column(table, "audiencia_hora"):
        op.add_column(table, sa.Column("audiencia_hora", sa.String(), nullable=True))

    if not _has_column(table, "audiencia_link"):
        op.add_column(table, sa.Column("audiencia_link", sa.String(), nullable=True))

    if not _has_column(table, "classifications"):
        op.add_column(table, sa.Column("classifications", sa.JSON(), nullable=True))


def downgrade() -> None:
    table = "publicacao_registros"
    for col in ("classifications", "audiencia_link", "audiencia_hora", "audiencia_data"):
        if _has_column(table, col):
            op.drop_column(table, col)
