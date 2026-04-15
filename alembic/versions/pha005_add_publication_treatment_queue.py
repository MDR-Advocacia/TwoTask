"""add publication treatment queue

Revision ID: pha005
Revises: pha004
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa


revision = "pha005"
down_revision = "pha004"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_index(table: str, index: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(row["name"] == index for row in inspector.get_indexes(table))


def _cleanup_orphan_type(name: str) -> None:
    """Remove composite types left over from failed prior CREATE TABLE runs.

    Postgres automatically creates a row type for every table. If a previous
    migration attempt failed after the type was registered but before the
    table was committed, the type lingers and blocks the next CREATE TABLE
    with "duplicate key value violates unique constraint pg_type_typname_nsp_index".
    """
    bind = op.get_bind()
    type_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :n"), {"n": name}
    ).scalar()
    if type_exists and not _has_table(name):
        bind.execute(sa.text(f'DROP TYPE IF EXISTS "{name}" CASCADE'))


def upgrade() -> None:
    _cleanup_orphan_type("publicacao_tratamento_execucoes")
    _cleanup_orphan_type("publicacao_tratamento_itens")

    if not _has_table("publicacao_tratamento_execucoes"):
        op.create_table(
            "publicacao_tratamento_execucoes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("status", sa.String(), nullable=False, server_default="INICIANDO"),
            sa.Column("trigger_type", sa.String(), nullable=False, server_default="MANUAL"),
            sa.Column("triggered_by_email", sa.String(), nullable=True),
            sa.Column("automation_id", sa.Integer(), sa.ForeignKey("scheduled_automations.id"), nullable=True),
            sa.Column("input_file_path", sa.String(), nullable=True),
            sa.Column("status_file_path", sa.String(), nullable=True),
            sa.Column("control_file_path", sa.String(), nullable=True),
            sa.Column("log_file_path", sa.String(), nullable=True),
            sa.Column("error_log_file_path", sa.String(), nullable=True),
            sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("retry_pending_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("batch_size", sa.Integer(), nullable=True),
            sa.Column("total_batches", sa.Integer(), nullable=True),
            sa.Column("current_batch", sa.Integer(), nullable=True),
            sa.Column("max_attempts", sa.Integer(), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sleep_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_pub_trat_exec_status", "publicacao_tratamento_execucoes", ["status"])
        op.create_index("ix_pub_trat_exec_triggered_by", "publicacao_tratamento_execucoes", ["triggered_by_email"])
        op.create_index("ix_pub_trat_exec_automation", "publicacao_tratamento_execucoes", ["automation_id"])

    if not _has_table("publicacao_tratamento_itens"):
        op.create_table(
            "publicacao_tratamento_itens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "publication_record_id",
                sa.Integer(),
                sa.ForeignKey("publicacao_registros.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("legal_one_update_id", sa.Integer(), nullable=False),
            sa.Column("linked_lawsuit_id", sa.Integer(), nullable=True),
            sa.Column("linked_lawsuit_cnj", sa.String(), nullable=True),
            sa.Column("linked_office_id", sa.Integer(), nullable=True),
            sa.Column("publication_date", sa.String(), nullable=True),
            sa.Column("source_record_status", sa.String(), nullable=False),
            sa.Column("target_status", sa.String(), nullable=False),
            sa.Column("queue_status", sa.String(), nullable=False, server_default="PENDENTE"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "last_run_id",
                sa.Integer(),
                sa.ForeignKey("publicacao_tratamento_execucoes.id"),
                nullable=True,
            ),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("treated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_response", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("publication_record_id", name="uq_pub_trat_record"),
            sa.UniqueConstraint("legal_one_update_id", name="uq_pub_trat_update"),
        )
        op.create_index("ix_pub_trat_item_lawsuit", "publicacao_tratamento_itens", ["linked_lawsuit_id"])
        op.create_index("ix_pub_trat_item_cnj", "publicacao_tratamento_itens", ["linked_lawsuit_cnj"])
        op.create_index("ix_pub_trat_item_office", "publicacao_tratamento_itens", ["linked_office_id"])
        op.create_index("ix_pub_trat_item_pub_date", "publicacao_tratamento_itens", ["publication_date"])
        op.create_index("ix_pub_trat_item_source_status", "publicacao_tratamento_itens", ["source_record_status"])
        op.create_index("ix_pub_trat_item_target_status", "publicacao_tratamento_itens", ["target_status"])
        op.create_index("ix_pub_trat_item_queue_status", "publicacao_tratamento_itens", ["queue_status"])
        op.create_index("ix_pub_trat_item_last_run", "publicacao_tratamento_itens", ["last_run_id"])


def downgrade() -> None:
    if _has_table("publicacao_tratamento_itens"):
        for index_name in (
            "ix_pub_trat_item_last_run",
            "ix_pub_trat_item_queue_status",
            "ix_pub_trat_item_target_status",
            "ix_pub_trat_item_source_status",
            "ix_pub_trat_item_pub_date",
            "ix_pub_trat_item_office",
            "ix_pub_trat_item_cnj",
            "ix_pub_trat_item_lawsuit",
        ):
            if _has_index("publicacao_tratamento_itens", index_name):
                op.drop_index(index_name, table_name="publicacao_tratamento_itens")
        op.drop_table("publicacao_tratamento_itens")

    if _has_table("publicacao_tratamento_execucoes"):
        for index_name in (
            "ix_pub_trat_exec_automation",
            "ix_pub_trat_exec_triggered_by",
            "ix_pub_trat_exec_status",
        ):
            if _has_index("publicacao_tratamento_execucoes", index_name):
                op.drop_index(index_name, table_name="publicacao_tratamento_execucoes")
        op.drop_table("publicacao_tratamento_execucoes")
