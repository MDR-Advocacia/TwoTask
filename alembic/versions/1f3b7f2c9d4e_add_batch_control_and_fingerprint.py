"""add batch control and fingerprint

Revision ID: 1f3b7f2c9d4e
Revises: e54506fdc4ab
Create Date: 2026-03-18 08:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1f3b7f2c9d4e"
down_revision: Union[str, Sequence[str], None] = "e54506fdc4ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("lotes_execucao", schema=None) as batch_op:
        batch_op.add_column(sa.Column("processor_type", sa.String(), nullable=False, server_default="GENERIC"))
        batch_op.add_column(sa.Column("source_filename", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("requested_by_email", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(), nullable=False, server_default="PENDENTE"))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("worker_id", sa.String(), nullable=True))
        batch_op.create_index(batch_op.f("ix_lotes_execucao_processor_type"), ["processor_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_lotes_execucao_requested_by_email"), ["requested_by_email"], unique=False)
        batch_op.create_index(batch_op.f("ix_lotes_execucao_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_lotes_execucao_heartbeat_at"), ["heartbeat_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_lotes_execucao_lease_expires_at"), ["lease_expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_lotes_execucao_worker_id"), ["worker_id"], unique=False)

    with op.batch_alter_table("lotes_itens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fingerprint", sa.String(), nullable=True))
        batch_op.create_index(batch_op.f("ix_lotes_itens_fingerprint"), ["fingerprint"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("lotes_itens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lotes_itens_fingerprint"))
        batch_op.drop_column("fingerprint")

    with op.batch_alter_table("lotes_execucao", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lotes_execucao_worker_id"))
        batch_op.drop_index(batch_op.f("ix_lotes_execucao_lease_expires_at"))
        batch_op.drop_index(batch_op.f("ix_lotes_execucao_heartbeat_at"))
        batch_op.drop_index(batch_op.f("ix_lotes_execucao_status"))
        batch_op.drop_index(batch_op.f("ix_lotes_execucao_requested_by_email"))
        batch_op.drop_index(batch_op.f("ix_lotes_execucao_processor_type"))
        batch_op.drop_column("worker_id")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("status")
        batch_op.drop_column("requested_by_email")
        batch_op.drop_column("source_filename")
        batch_op.drop_column("processor_type")
