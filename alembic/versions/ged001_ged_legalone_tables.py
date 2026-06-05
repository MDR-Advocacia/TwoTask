"""ged001: tabelas do modulo GED LegalOne (envio em lote pro GED do L1).

Revision ID: ged001
Revises: tax013
Create Date: 2026-06-04

Cria 2 tabelas pra o envio em lote de arquivos pro GED (ECM) do Legal One
a partir de CNJ + arquivo:

- ged_upload_batch: cabecalho do lote (modo SINGLE_FILE/MULTI_FILE, tipo no
  GED, status, contadores denormalizados, arquivo compartilhado no modo
  SINGLE_FILE).
- ged_upload_item: 1 linha por (CNJ, arquivo). Status + ged_document_id por
  item; ged_document_id e' a chave de idempotencia (item enviado nunca
  re-sobe num retry).

head atual = tax013 (conferido via `alembic heads`/`alembic current` no
container onetask-api-1). Single head, sem merge necessario.
"""

from alembic import op
import sqlalchemy as sa


revision = "ged001"
down_revision = "tax013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ged_upload_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("type_id", sa.String(16), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("total_itens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sucesso", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_erro", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_pendente", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shared_file_path", sa.String(512), nullable=True),
        sa.Column("shared_file_sha256", sa.String(64), nullable=True),
        sa.Column("shared_original_filename", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolving_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ged_upload_batch_status",
        "ged_upload_batch",
        ["status"],
    )

    op.create_table(
        "ged_upload_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("ged_upload_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cnj_number", sa.String(64), nullable=True),
        sa.Column("lawsuit_id", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("file_ext", sa.String(16), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="PENDENTE",
        ),
        sa.Column("ged_document_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ged_upload_item_batch_id",
        "ged_upload_item",
        ["batch_id"],
    )
    op.create_index(
        "ix_ged_upload_item_cnj_number",
        "ged_upload_item",
        ["cnj_number"],
    )
    op.create_index(
        "ix_ged_upload_item_sha256",
        "ged_upload_item",
        ["sha256"],
    )
    op.create_index(
        "ix_ged_upload_item_status",
        "ged_upload_item",
        ["status"],
    )
    op.create_index(
        "ix_ged_upload_item_batch_status",
        "ged_upload_item",
        ["batch_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_ged_upload_item_batch_status", "ged_upload_item")
    op.drop_index("ix_ged_upload_item_status", "ged_upload_item")
    op.drop_index("ix_ged_upload_item_sha256", "ged_upload_item")
    op.drop_index("ix_ged_upload_item_cnj_number", "ged_upload_item")
    op.drop_index("ix_ged_upload_item_batch_id", "ged_upload_item")
    op.drop_table("ged_upload_item")

    op.drop_index("ix_ged_upload_batch_status", "ged_upload_batch")
    op.drop_table("ged_upload_batch")
