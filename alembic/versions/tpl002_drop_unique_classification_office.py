"""drop unique constraint on task_templates (category, subcategory, office)

Permite múltiplos templates para a mesma (categoria, subcategoria, escritório),
diferenciados pelo task_subtype — um template conceitual pode gerar N tarefas.

Revision ID: tpl002_drop_uq_clf_office
Revises: pha005
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op


revision: str = "tpl002_drop_uq_clf_office"
down_revision: Union[str, Sequence[str], None] = "pha005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_task_template_classification_office",
        "task_templates",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_task_template_classification_office",
        "task_templates",
        ["category", "subcategory", "office_external_id"],
    )
