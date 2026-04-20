"""add prazo inicial legacy task cancellation queue

Revision ID: pin006
Revises: pin005
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "pin006"
down_revision = "pin005"
branch_labels = None
depends_on = None


TABLE = "prazo_inicial_legacy_task_cancel_items"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_index(table: str, index: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(row["name"] == index for row in inspector.get_indexes(table))


def upgrade() -> None:
    if _has_table(TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "intake_id",
            sa.Integer(),
            sa.ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lawsuit_id", sa.Integer(), nullable=True),
        sa.Column("cnj_number", sa.String(length=32), nullable=True),
        sa.Column("office_id", sa.Integer(), nullable=True),
        sa.Column("legacy_task_type_external_id", sa.Integer(), nullable=False, server_default="33"),
        sa.Column("legacy_task_subtype_external_id", sa.Integer(), nullable=False, server_default="1283"),
        sa.Column("queue_status", sa.String(length=24), nullable=False, server_default="PENDENTE"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_task_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_task_id", sa.Integer(), nullable=True),
        sa.Column("last_reason", sa.String(length=64), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("intake_id", name="uq_pin_legacy_task_cancel_intake"),
    )
    op.create_index("ix_pin_legacy_cancel_lawsuit", TABLE, ["lawsuit_id"])
    op.create_index("ix_pin_legacy_cancel_cnj", TABLE, ["cnj_number"])
    op.create_index("ix_pin_legacy_cancel_office", TABLE, ["office_id"])
    op.create_index("ix_pin_legacy_cancel_queue_status", TABLE, ["queue_status"])
    op.create_index("ix_pin_legacy_cancel_selected_task", TABLE, ["selected_task_id"])
    op.create_index("ix_pin_legacy_cancel_cancelled_task", TABLE, ["cancelled_task_id"])
    op.create_index("ix_pin_legacy_cancel_last_reason", TABLE, ["last_reason"])


def downgrade() -> None:
    if not _has_table(TABLE):
        return

    for index_name in (
        "ix_pin_legacy_cancel_last_reason",
        "ix_pin_legacy_cancel_cancelled_task",
        "ix_pin_legacy_cancel_selected_task",
        "ix_pin_legacy_cancel_queue_status",
        "ix_pin_legacy_cancel_office",
        "ix_pin_legacy_cancel_cnj",
        "ix_pin_legacy_cancel_lawsuit",
    ):
        if _has_index(TABLE, index_name):
            op.drop_index(index_name, table_name=TABLE)
    op.drop_table(TABLE)
