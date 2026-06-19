"""Publicações: auditoria do payload enviado ao L1 + quem agendou/modificou

Revision ID: pub004_publication_task_audit
Revises: onr002_anotacoes
Create Date: 2026-06-19

Tabela append-only que registra, por tarefa criada no L1, o payload EXATO
enviado, a proposta automática, o diff (override humano) e quem agendou.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "pub004_publication_task_audit"
down_revision = "onr002_anotacoes"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table)


def upgrade() -> None:
    if _has_table("publicacao_tarefa_audit"):
        return
    op.create_table(
        "publicacao_tarefa_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lawsuit_id", sa.Integer(), nullable=True),
        sa.Column("publication_record_id", sa.Integer(), nullable=True),
        sa.Column("subtype_id", sa.Integer(), nullable=True),
        sa.Column("created_task_id", sa.Integer(), nullable=True),
        sa.Column("sent_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("proposed_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("override_detected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("override_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scheduled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_by_name", sa.String(), nullable=True),
        sa.Column("scheduled_by_email", sa.String(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pub_tarefa_audit_id", "publicacao_tarefa_audit", ["id"])
    op.create_index("ix_pub_tarefa_audit_lawsuit", "publicacao_tarefa_audit", ["lawsuit_id"])
    op.create_index("ix_pub_tarefa_audit_record", "publicacao_tarefa_audit", ["publication_record_id"])
    op.create_index("ix_pub_tarefa_audit_task", "publicacao_tarefa_audit", ["created_task_id"])
    op.create_index("ix_pub_tarefa_audit_override", "publicacao_tarefa_audit", ["override_detected"])
    op.create_index("ix_pub_tarefa_audit_sched_by", "publicacao_tarefa_audit", ["scheduled_by_user_id"])


def downgrade() -> None:
    if not _has_table("publicacao_tarefa_audit"):
        return
    for idx in (
        "ix_pub_tarefa_audit_sched_by",
        "ix_pub_tarefa_audit_override",
        "ix_pub_tarefa_audit_task",
        "ix_pub_tarefa_audit_record",
        "ix_pub_tarefa_audit_lawsuit",
        "ix_pub_tarefa_audit_id",
    ):
        op.drop_index(idx, table_name="publicacao_tarefa_audit")
    op.drop_table("publicacao_tarefa_audit")
