"""Adiciona coluna `natureza_processo` em publicacao_registros

Revision ID: perf003_natureza_processo
Revises: perf002_uf_column
Create Date: 2026-04-16

Motivação
---------
Publicações sem pasta de processo vinculada (linked_lawsuit_id IS NULL)
precisam de tratamento especializado. A natureza do processo é detectada
automaticamente pelo classificador IA a partir do texto da publicação
(ex.: "Embargos à Execução", "Agravo de Instrumento") e gravada neste
campo para filtragem e triagem na tela de publicações.
"""

from alembic import op
import sqlalchemy as sa

revision = "perf003_natureza_processo"
down_revision = "perf002_uf_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publicacao_registros",
        sa.Column("natureza_processo", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_publicacao_registros_natureza_processo",
        "publicacao_registros",
        ["natureza_processo"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publicacao_registros_natureza_processo",
        table_name="publicacao_registros",
    )
    op.drop_column("publicacao_registros", "natureza_processo")
