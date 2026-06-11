"""con001: tabelas do modulo Atualizacao de Contatos LegalOne.

Revision ID: con001
Revises: sso001
Create Date: 2026-06-11

Cria 2 tabelas pro enriquecimento em lote de contatos no Legal One
(telefones/e-mail/endereco gravados via navigation property POST, a partir
de um CSV Dossie com CPF/CNPJ):

- contato_atualizacao_batch: cabecalho do lote (status, dry_run, contadores
  denormalizados, metadados do arquivo).
- contato_atualizacao_item: 1 linha do CSV. Guarda o payload parseado
  (payload_json), o id do contato resolvido e o relatorio do que foi
  criado/pulado (result_json).

head atual = sso001 (conferido via `alembic heads` no container
onetask-api-1). Single head, sem merge necessario.
"""

from alembic import op
import sqlalchemy as sa


revision = "con001"
down_revision = "sso001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contato_atualizacao_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "dry_run", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="PROCESSING",
        ),
        sa.Column("total_itens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sucesso", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_erro", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_pendente", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_filename", sa.String(255), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
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
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_contato_atualizacao_batch_status",
        "contato_atualizacao_batch",
        ["status"],
    )

    op.create_table(
        "contato_atualizacao_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("contato_atualizacao_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("doc_number", sa.String(32), nullable=False),
        sa.Column("doc_digits", sa.String(20), nullable=True),
        sa.Column("doc_kind", sa.String(8), nullable=False),
        sa.Column("nome_abreviado", sa.String(255), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="PENDENTE",
        ),
        sa.Column("result_json", sa.JSON(), nullable=True),
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
        "ix_contato_atualizacao_item_batch_id",
        "contato_atualizacao_item",
        ["batch_id"],
    )
    op.create_index(
        "ix_contato_atualizacao_item_doc_number",
        "contato_atualizacao_item",
        ["doc_number"],
    )
    op.create_index(
        "ix_contato_atualizacao_item_doc_digits",
        "contato_atualizacao_item",
        ["doc_digits"],
    )
    op.create_index(
        "ix_contato_atualizacao_item_status",
        "contato_atualizacao_item",
        ["status"],
    )
    op.create_index(
        "ix_contato_atualizacao_item_batch_status",
        "contato_atualizacao_item",
        ["batch_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_contato_atualizacao_item_batch_status", "contato_atualizacao_item")
    op.drop_index("ix_contato_atualizacao_item_status", "contato_atualizacao_item")
    op.drop_index("ix_contato_atualizacao_item_doc_digits", "contato_atualizacao_item")
    op.drop_index("ix_contato_atualizacao_item_doc_number", "contato_atualizacao_item")
    op.drop_index("ix_contato_atualizacao_item_batch_id", "contato_atualizacao_item")
    op.drop_table("contato_atualizacao_item")

    op.drop_index("ix_contato_atualizacao_batch_status", "contato_atualizacao_batch")
    op.drop_table("contato_atualizacao_batch")
