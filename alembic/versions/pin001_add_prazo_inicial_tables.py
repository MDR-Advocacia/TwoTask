"""add prazo inicial tables

Revision ID: pin001
Revises: usr002
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "pin001"
down_revision = "fb001_classification_feedback"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(table: str, index: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(row["name"] == index for row in inspector.get_indexes(table))


def _cleanup_orphan_type(name: str) -> None:
    bind = op.get_bind()
    type_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :n"), {"n": name}
    ).scalar()
    if type_exists and not _has_table(name):
        bind.execute(sa.text(f'DROP TYPE IF EXISTS "{name}" CASCADE'))


def upgrade() -> None:
    # ── Permissão no legal_one_users ──────────────────────────────────
    if not _has_column("legal_one_users", "can_use_prazos_iniciais"):
        op.add_column(
            "legal_one_users",
            sa.Column(
                "can_use_prazos_iniciais",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # ── prazo_inicial_batches ─────────────────────────────────────────
    _cleanup_orphan_type("prazo_inicial_batches")
    if not _has_table("prazo_inicial_batches"):
        op.create_table(
            "prazo_inicial_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("anthropic_batch_id", sa.String(), nullable=True),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="ENVIADO",
            ),
            sa.Column("anthropic_status", sa.String(), nullable=True),
            sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("succeeded_count", sa.Integer(), server_default="0"),
            sa.Column("errored_count", sa.Integer(), server_default="0"),
            sa.Column("expired_count", sa.Integer(), server_default="0"),
            sa.Column("canceled_count", sa.Integer(), server_default="0"),
            sa.Column("intake_ids", sa.JSON(), nullable=True),
            sa.Column("batch_metadata", sa.JSON(), nullable=True),
            sa.Column("model_used", sa.String(), nullable=True),
            sa.Column("requested_by_email", sa.String(), nullable=True),
            sa.Column("results_url", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_pin_batches_anthropic_id",
            "prazo_inicial_batches",
            ["anthropic_batch_id"],
        )
        op.create_index(
            "ix_pin_batches_status", "prazo_inicial_batches", ["status"]
        )
        op.create_index(
            "ix_pin_batches_requested_by",
            "prazo_inicial_batches",
            ["requested_by_email"],
        )

    # ── prazo_inicial_intakes ─────────────────────────────────────────
    _cleanup_orphan_type("prazo_inicial_intakes")
    if not _has_table("prazo_inicial_intakes"):
        op.create_table(
            "prazo_inicial_intakes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("external_id", sa.String(length=255), nullable=False),
            sa.Column("cnj_number", sa.String(length=32), nullable=False),
            sa.Column("lawsuit_id", sa.Integer(), nullable=True),
            sa.Column("office_id", sa.Integer(), nullable=True),
            sa.Column("capa_json", sa.JSON(), nullable=False),
            sa.Column("integra_json", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("pdf_path", sa.String(length=512), nullable=True),
            sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
            sa.Column("pdf_bytes", sa.BigInteger(), nullable=True),
            sa.Column("pdf_filename_original", sa.String(length=255), nullable=True),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="RECEBIDO",
            ),
            sa.Column(
                "classification_batch_id",
                sa.Integer(),
                sa.ForeignKey(
                    "prazo_inicial_batches.id", ondelete="SET NULL"
                ),
                nullable=True,
            ),
            sa.Column("ged_document_id", sa.Integer(), nullable=True),
            sa.Column("ged_uploaded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("external_id", name="uq_pin_intakes_external_id"),
        )
        op.create_index(
            "ix_pin_intakes_external_id",
            "prazo_inicial_intakes",
            ["external_id"],
        )
        op.create_index(
            "ix_pin_intakes_cnj", "prazo_inicial_intakes", ["cnj_number"]
        )
        op.create_index(
            "ix_pin_intakes_lawsuit_id",
            "prazo_inicial_intakes",
            ["lawsuit_id"],
        )
        op.create_index(
            "ix_pin_intakes_office_id",
            "prazo_inicial_intakes",
            ["office_id"],
        )
        op.create_index(
            "ix_pin_intakes_status", "prazo_inicial_intakes", ["status"]
        )
        op.create_index(
            "ix_pin_intakes_batch_id",
            "prazo_inicial_intakes",
            ["classification_batch_id"],
        )

    # ── prazo_inicial_sugestoes ───────────────────────────────────────
    _cleanup_orphan_type("prazo_inicial_sugestoes")
    if not _has_table("prazo_inicial_sugestoes"):
        op.create_table(
            "prazo_inicial_sugestoes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "intake_id",
                sa.Integer(),
                sa.ForeignKey(
                    "prazo_inicial_intakes.id", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column("tipo_prazo", sa.String(length=64), nullable=False),
            sa.Column("subtipo", sa.String(length=128), nullable=True),
            sa.Column("data_base", sa.Date(), nullable=True),
            sa.Column("prazo_dias", sa.Integer(), nullable=True),
            sa.Column("prazo_tipo", sa.String(length=16), nullable=True),
            sa.Column("data_final_calculada", sa.Date(), nullable=True),
            sa.Column("audiencia_data", sa.Date(), nullable=True),
            sa.Column("audiencia_hora", sa.Time(), nullable=True),
            sa.Column("audiencia_link", sa.Text(), nullable=True),
            sa.Column("confianca", sa.String(length=16), nullable=True),
            sa.Column("justificativa", sa.Text(), nullable=True),
            sa.Column("responsavel_sugerido_id", sa.Integer(), nullable=True),
            sa.Column("task_type_id", sa.Integer(), nullable=True),
            sa.Column("task_subtype_id", sa.Integer(), nullable=True),
            sa.Column("payload_proposto", sa.JSON(), nullable=True),
            sa.Column(
                "review_status",
                sa.String(length=16),
                nullable=False,
                server_default="pendente",
            ),
            sa.Column("reviewed_by_email", sa.String(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_task_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_pin_sugestoes_intake",
            "prazo_inicial_sugestoes",
            ["intake_id"],
        )
        op.create_index(
            "ix_pin_sugestoes_tipo",
            "prazo_inicial_sugestoes",
            ["tipo_prazo"],
        )
        op.create_index(
            "ix_pin_sugestoes_review_status",
            "prazo_inicial_sugestoes",
            ["review_status"],
        )


def downgrade() -> None:
    if _has_table("prazo_inicial_sugestoes"):
        op.drop_table("prazo_inicial_sugestoes")
    if _has_table("prazo_inicial_intakes"):
        op.drop_table("prazo_inicial_intakes")
    if _has_table("prazo_inicial_batches"):
        op.drop_table("prazo_inicial_batches")
    if _has_column("legal_one_users", "can_use_prazos_iniciais"):
        op.drop_column("legal_one_users", "can_use_prazos_iniciais")
