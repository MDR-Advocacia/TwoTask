"""add natureza_aplicavel to prazo_inicial_task_templates

Fase 3c — nova coluna `natureza_aplicavel` (NULL = qualquer natureza;
valor = casa só com intakes dessa natureza) entra como parte da chave
única. Templates existentes (pós pin002) mantêm `natureza_aplicavel=NULL`
e continuam funcionando como genéricos.

Chave antiga:  (tipo_prazo, subtipo, office_external_id)
Chave nova:    (tipo_prazo, subtipo, natureza_aplicavel, office_external_id)

Usa batch_alter_table pra compatibilidade com SQLite (ambiente de testes).

Revision ID: pin004
Revises: pin003
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "pin004"
down_revision = "pin003"
branch_labels = None
depends_on = None


OLD_UQ = "uq_pin_task_templates_tipo_subtipo_office"
NEW_UQ = "uq_pin_task_templates_tipo_subtipo_natureza_office"
TABLE = "prazo_inicial_task_templates"


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_unique(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        uq["name"] == name for uq in inspector.get_unique_constraints(table)
    )


def upgrade() -> None:
    # 1) adiciona coluna (fora do batch pra evitar recriação desnecessária).
    if not _has_column(TABLE, "natureza_aplicavel"):
        op.add_column(
            TABLE,
            sa.Column("natureza_aplicavel", sa.String(length=64), nullable=True),
        )

    # 2) recria UNIQUE constraint incluindo natureza_aplicavel. batch_alter_table
    # garante compatibilidade com SQLite (que não suporta ALTER CONSTRAINT).
    with op.batch_alter_table(TABLE) as batch:
        if _has_unique(TABLE, OLD_UQ):
            batch.drop_constraint(OLD_UQ, type_="unique")
        if not _has_unique(TABLE, NEW_UQ):
            batch.create_unique_constraint(
                NEW_UQ,
                [
                    "tipo_prazo",
                    "subtipo",
                    "natureza_aplicavel",
                    "office_external_id",
                ],
            )

    # 3) index utilitário (query comum: listar templates de uma natureza).
    op.create_index(
        "ix_pin_task_templates_natureza",
        TABLE,
        ["natureza_aplicavel"],
        if_not_exists=True,
    )


def downgrade() -> None:
    # Remove index e reverte UNIQUE pra forma original.
    op.drop_index(
        "ix_pin_task_templates_natureza",
        table_name=TABLE,
        if_exists=True,
    )
    with op.batch_alter_table(TABLE) as batch:
        if _has_unique(TABLE, NEW_UQ):
            batch.drop_constraint(NEW_UQ, type_="unique")
        if not _has_unique(TABLE, OLD_UQ):
            batch.create_unique_constraint(
                OLD_UQ,
                ["tipo_prazo", "subtipo", "office_external_id"],
            )
    if _has_column(TABLE, "natureza_aplicavel"):
        op.drop_column(TABLE, "natureza_aplicavel")
