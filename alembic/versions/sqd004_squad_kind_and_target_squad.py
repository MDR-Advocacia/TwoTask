"""squads.kind ('principal' | 'support') + target_squad_id em templates

Squads agora tem 2 tipos:
  - 'principal' (default): 1 por escritorio, recebe tarefas via responsavel
    da pasta + assistente da squad do responsavel
  - 'support': N por escritorio, transversais. Cada uma com seu nome livre,
    1 leader + N assistentes (round-robin). Usadas em templates pra
    direcionar tarefas especificas (ex.: "Analise Recursal" sempre cai
    pra um analista recursal de plantao, independente do responsavel
    da pasta).

Templates ganham `target_squad_id` (FK pra squads.id, nullable):
  - target_squad_id=NULL + target_role='principal' → responsavel padrao
  - target_squad_id=NULL + target_role='assistente' → assistente da squad
    PRINCIPAL do responsavel (lógica atual)
  - target_squad_id=X + target_role='principal' → leader da squad de
    suporte X
  - target_squad_id=X + target_role='assistente' → assistente da squad
    de suporte X (round-robin)

Decisao tomada com user em 2026-05-04: squads de suporte tambem sao por
escritorio responsavel, mantem `office_external_id` no schema.

Revision ID: sqd004
Revises: sqd003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "sqd004"
down_revision: Union[str, None] = "sqd003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Discriminador da squad
    op.add_column(
        "squads",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="principal",
        ),
    )
    op.create_check_constraint(
        "ck_squads_kind",
        "squads",
        "kind IN ('principal', 'support')",
    )
    op.create_index("ix_squads_kind", "squads", ["kind"])

    # 2) target_squad_id em ambas as tabelas de template
    for table in ("prazo_inicial_task_templates", "task_templates"):
        op.add_column(
            table,
            sa.Column(
                "target_squad_id",
                sa.Integer(),
                sa.ForeignKey(
                    "squads.id",
                    name=f"fk_{table}_target_squad_id",
                ),
                nullable=True,
            ),
        )
        op.create_index(
            f"ix_{table}_target_squad_id",
            table,
            ["target_squad_id"],
        )


def downgrade() -> None:
    for table in ("prazo_inicial_task_templates", "task_templates"):
        op.drop_index(f"ix_{table}_target_squad_id", table_name=table)
        op.drop_constraint(f"fk_{table}_target_squad_id", table, type_="foreignkey")
        op.drop_column(table, "target_squad_id")

    op.drop_index("ix_squads_kind", table_name="squads")
    op.drop_constraint("ck_squads_kind", "squads", type_="check")
    op.drop_column("squads", "kind")
