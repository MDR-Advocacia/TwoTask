"""relaxa NOT NULL de task_templates.responsible_user_external_id

Templates agora podem ser criados sem responsável nominal. O frontend
cobra o preenchimento no momento de criar a tarefa (modal de
CreateTaskByProcessPage). Motivação: responsável da pasta do processo
só é conhecido no momento da classificação — exigi-lo no template gera
atrito desnecessário no cadastro.

Revision ID: tpl004
Revises: pin006
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "tpl004"
down_revision: Union[str, None] = "pin006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "task_templates",
        "responsible_user_external_id",
        existing_type=None,
        nullable=True,
    )


def downgrade() -> None:
    # Importante: antes de voltar pra NOT NULL seria necessário
    # garantir que não existem templates com responsável NULL.
    # Pra um downgrade seguro, definir o responsável em todos os
    # registros antes de rodar este comando.
    op.alter_column(
        "task_templates",
        "responsible_user_external_id",
        existing_type=None,
        nullable=False,
    )
