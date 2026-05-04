"""refactor: Squad usa office_external_id em vez de sector_id (drop Sector)

Decisao tomada com user em 2026-05-04: o conceito de `Sector` (Civel,
Trabalhista) duplica a hierarquia de escritorios (`LegalOneOffice` com
path "MDR / Filial BA / Civel"). Todo o dominio operacional ja' usa
`office_external_id`:
- task_templates (publicacoes)
- prazo_inicial_task_templates
- LegalOneUser.default_office_id
- PublicationRecord.linked_office_id
- prazo_inicial_intakes.office_id

Squad era a unica entidade que pendurava em Sector. Esse refactor alinha:
  Squad.sector_id -> Squad.office_external_id (FK pra legal_one_offices)

Como prod nao tem squads/sectors cadastrados (verificado), faco clean
break: dropa sector_id, dropa tabela sectors. Endpoints /sectors e o
sector_service ficam mortos no codigo (apagados num commit pareado).

Tie-break do `resolve_assistant` muda: quando user e' membro de varias
squads, casa `Squad.office_external_id` com `intake.office_id` /
`sugestao.office_external_id` em vez do M2M Squad↔TaskType.

Revision ID: sqd002
Revises: sqd001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "sqd002"
down_revision: Union[str, None] = "sqd001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Adiciona office_external_id (FK pra legal_one_offices.external_id).
    # Nullable=False — clean break (prod confirmado sem squads ativas).
    op.add_column(
        "squads",
        sa.Column(
            "office_external_id",
            sa.Integer(),
            sa.ForeignKey(
                "legal_one_offices.external_id",
                name="fk_squads_office_external_id",
            ),
            nullable=True,  # Nullable na migration; o codigo Python valida.
        ),
    )
    op.create_index(
        "ix_squads_office_external_id",
        "squads",
        ["office_external_id"],
    )

    # 2) Drop a M2M `squad_task_type_association` — agora o tie-break do
    # resolver usa office_external_id, nao mais task_types da squad.
    # Safe: M2M nao e' lida em outro lugar alem do resolver e da tab
    # AssociateTasks (que vai ser refatorada pra usar office tb).
    op.drop_table("squad_task_type_association")

    # 3) Drop sector_id da squads + drop tabela sectors.
    op.drop_constraint("squads_sector_id_fkey", "squads", type_="foreignkey")
    op.drop_column("squads", "sector_id")
    op.drop_table("sectors")


def downgrade() -> None:
    # Recreia sectors (vazia) + sector_id NOT NULL nas squads.
    op.create_table(
        "sectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "squads",
        sa.Column(
            "sector_id",
            sa.Integer(),
            sa.ForeignKey("sectors.id", name="squads_sector_id_fkey"),
            nullable=True,  # downgrade nao consegue reconstituir o mapping
        ),
    )

    op.create_table(
        "squad_task_type_association",
        sa.Column(
            "squad_id",
            sa.Integer(),
            sa.ForeignKey("squads.id"),
            primary_key=True,
        ),
        sa.Column(
            "task_type_external_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_task_types.external_id"),
            primary_key=True,
        ),
    )

    op.drop_index("ix_squads_office_external_id", table_name="squads")
    op.drop_constraint(
        "fk_squads_office_external_id", "squads", type_="foreignkey"
    )
    op.drop_column("squads", "office_external_id")
