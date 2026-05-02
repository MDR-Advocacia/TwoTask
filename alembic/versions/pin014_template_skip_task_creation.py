"""template no-op: skip_task_creation em prazo_inicial_task_templates

Permite cadastrar template que CASA com (tipo_prazo, subtipo, natureza,
office) mas NAO cria tarefa no L1 — usado pra finalizar caso sem
providencia automaticamente quando a IA classifica algo conhecido (ex.:
SEM_PRAZO_EM_ABERTO/INDETERMINADO + motivo recorrente). Mesmo terminal
do "Finalizar sem providencia" manual: intake vira
CONCLUIDO_SEM_PROVIDENCIA, dispatch_pending=True, GED upload + cancel
da legacy task acontecem normalmente.

Quando skip_task_creation=TRUE, os campos de tarefa
(task_subtype_external_id, responsible_user_external_id) ficam NULL —
relaxamos o NOT NULL e adicionamos CheckConstraint pra garantir que
template "normal" (skip=FALSE) ainda exige os dois preenchidos.

Revision ID: pin014
Revises: pin013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "pin014"
down_revision: Union[str, None] = "pin013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prazo_inicial_task_templates",
        sa.Column(
            "skip_task_creation",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.alter_column(
        "prazo_inicial_task_templates",
        "task_subtype_external_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "prazo_inicial_task_templates",
        "responsible_user_external_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_pin_task_templates_skip_or_task_fields",
        "prazo_inicial_task_templates",
        (
            "(skip_task_creation = TRUE) OR ("
            "task_subtype_external_id IS NOT NULL AND "
            "responsible_user_external_id IS NOT NULL)"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_pin_task_templates_skip_or_task_fields",
        "prazo_inicial_task_templates",
        type_="check",
    )
    # Restaurar NOT NULL — pressupõe que rows com skip_task_creation=TRUE
    # tenham sido removidas antes do downgrade (ou ja tenham task_*
    # preenchidos). Sem isso, o ALTER falha.
    op.alter_column(
        "prazo_inicial_task_templates",
        "responsible_user_external_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "prazo_inicial_task_templates",
        "task_subtype_external_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("prazo_inicial_task_templates", "skip_task_creation")
