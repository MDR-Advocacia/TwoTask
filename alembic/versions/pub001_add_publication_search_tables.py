"""add publication search tables

Revision ID: pub001_publication_search
Revises: clf001_classification
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "pub001_publication_search"
down_revision: Union[str, Sequence[str], None] = "clf001_classification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publicacao_buscas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDENTE"),
        sa.Column("date_from", sa.String(), nullable=False),
        sa.Column("date_to", sa.String(), nullable=True),
        sa.Column("origin_type", sa.String(), nullable=False, server_default="OfficialJournalsCrawler"),
        sa.Column("office_filter", sa.String(), nullable=True),
        sa.Column("total_found", sa.Integer(), server_default="0"),
        sa.Column("total_new", sa.Integer(), server_default="0"),
        sa.Column("total_duplicate", sa.Integer(), server_default="0"),
        sa.Column("requested_by_email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
    )
    op.create_index("ix_publicacao_buscas_status", "publicacao_buscas", ["status"])
    op.create_index("ix_publicacao_buscas_requested_by_email", "publicacao_buscas", ["requested_by_email"])

    op.create_table(
        "publicacao_registros",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("search_id", sa.Integer(), sa.ForeignKey("publicacao_buscas.id"), nullable=False),
        sa.Column("legal_one_update_id", sa.Integer(), nullable=False),
        sa.Column("origin_type", sa.String(), nullable=True),
        sa.Column("update_type_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("publication_date", sa.String(), nullable=True),
        sa.Column("creation_date", sa.String(), nullable=True),
        sa.Column("linked_lawsuit_id", sa.Integer(), nullable=True),
        sa.Column("linked_lawsuit_cnj", sa.String(), nullable=True),
        sa.Column("linked_office_id", sa.Integer(), nullable=True),
        sa.Column("raw_relationships", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="NOVO"),
        sa.Column("is_duplicate", sa.Boolean(), server_default="0"),
        sa.Column("classification_item_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_publicacao_registros_legal_one_update_id", "publicacao_registros", ["legal_one_update_id"], unique=True)
    op.create_index("ix_publicacao_registros_search_id", "publicacao_registros", ["search_id"])
    op.create_index("ix_publicacao_registros_linked_lawsuit_id", "publicacao_registros", ["linked_lawsuit_id"])
    op.create_index("ix_publicacao_registros_linked_lawsuit_cnj", "publicacao_registros", ["linked_lawsuit_cnj"])
    op.create_index("ix_publicacao_registros_status", "publicacao_registros", ["status"])


def downgrade() -> None:
    op.drop_table("publicacao_registros")
    op.drop_table("publicacao_buscas")
