"""Add office_classification_overrides table and new fields

- Tabela office_classification_overrides para gestão de classificações por escritório
- Campo audiencia_link em publicacao_registros (link de videoconferência)
- Campo classifications em publicacao_registros (JSON - múltiplas classificações)
- Campo error_details em publicacao_batches_classificacao (JSON - erros por item)

Revision ID: feat002_clf_overrides
Revises: pol001_polo_field
Create Date: 2026-04-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "feat002_clf_overrides"
down_revision: Union[str, Sequence[str], None] = "pol001_polo_field"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cleanup: drop leftover temp table from any prior failed run
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_task_templates"))

    # 0. Tornar office_external_id nullable em task_templates
    #    (NULL = template global para publicações sem escritório/processo)
    with op.batch_alter_table("task_templates") as batch_op:
        batch_op.alter_column(
            "office_external_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    # 1. Tabela de overrides de classificação por escritório
    # (drop first in case prior failed run left it partially created)
    conn.execute(sa.text("DROP TABLE IF EXISTS office_classification_overrides"))
    op.create_table(
        "office_classification_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("office_external_id", sa.Integer(), sa.ForeignKey("legal_one_offices.external_id"), nullable=False, index=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False, server_default="exclude"),
        sa.Column("custom_description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "office_external_id", "category", "subcategory", "action",
            name="uq_office_clf_override",
        ),
    )

    # 2. Novos campos em publicacao_registros
    with op.batch_alter_table("publicacao_registros") as batch_op:
        batch_op.add_column(sa.Column("audiencia_link", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("classifications", sa.JSON(), nullable=True))

    # 3. Novo campo em publicacao_batches_classificacao
    with op.batch_alter_table("publicacao_batches_classificacao") as batch_op:
        batch_op.add_column(sa.Column("error_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("task_templates") as batch_op:
        batch_op.alter_column(
            "office_external_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    with op.batch_alter_table("publicacao_batches_classificacao") as batch_op:
        batch_op.drop_column("error_details")

    with op.batch_alter_table("publicacao_registros") as batch_op:
        batch_op.drop_column("classifications")
        batch_op.drop_column("audiencia_link")

    op.drop_table("office_classification_overrides")
