"""add prazo_inicial_task_templates

Tabela separada de `task_templates` (que serve o fluxo de publicações).
Espelha colunas principais mas usa (tipo_prazo, subtipo, office_external_id)
como chave de casamento com as sugestões geradas pela classificação de
prazos iniciais.

Revision ID: pin002
Revises: pin001
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "pin002"
down_revision = "pin001"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("prazo_inicial_task_templates"):
        return

    op.create_table(
        "prazo_inicial_task_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tipo_prazo", sa.String(length=64), nullable=False),
        sa.Column("subtipo", sa.String(length=128), nullable=True),
        sa.Column(
            "office_external_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_offices.external_id"),
            nullable=True,
        ),
        sa.Column(
            "task_subtype_external_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_task_subtypes.external_id"),
            nullable=False,
        ),
        sa.Column(
            "responsible_user_external_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.external_id"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.String(),
            nullable=False,
            server_default="Normal",
        ),
        sa.Column(
            "due_business_days",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "due_date_reference",
            sa.String(),
            nullable=False,
            server_default="data_base",
        ),
        sa.Column("description_template", sa.Text(), nullable=True),
        sa.Column("notes_template", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tipo_prazo",
            "subtipo",
            "office_external_id",
            name="uq_pin_task_templates_tipo_subtipo_office",
        ),
    )
    op.create_index(
        "ix_pin_task_templates_tipo",
        "prazo_inicial_task_templates",
        ["tipo_prazo"],
    )
    op.create_index(
        "ix_pin_task_templates_subtipo",
        "prazo_inicial_task_templates",
        ["subtipo"],
    )
    op.create_index(
        "ix_pin_task_templates_office",
        "prazo_inicial_task_templates",
        ["office_external_id"],
    )
    op.create_index(
        "ix_pin_task_templates_task_subtype",
        "prazo_inicial_task_templates",
        ["task_subtype_external_id"],
    )
    op.create_index(
        "ix_pin_task_templates_responsible",
        "prazo_inicial_task_templates",
        ["responsible_user_external_id"],
    )
    op.create_index(
        "ix_pin_task_templates_active",
        "prazo_inicial_task_templates",
        ["is_active"],
    )


def downgrade() -> None:
    if _has_table("prazo_inicial_task_templates"):
        op.drop_table("prazo_inicial_task_templates")
