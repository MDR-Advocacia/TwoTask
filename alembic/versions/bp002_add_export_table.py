"""bp002: cria tabela base_processual_export pra historico de relatorios

Revision ID: bp002
Revises: tax010
Create Date: 2026-05-11

1 tabela:
- base_processual_export: 1 row por relatorio solicitado, com status
  (PENDENTE/PROCESSANDO/PRONTO/FALHOU), template_name, params_json, e
  file_path apontando pro XLSX em volume.

Indices:
- status pra dashboard filtra "em processamento" / "falhou"
- requested_at pra ordenar por mais recente
- requested_by_user_id pra historico por operador (futuro)

Cleanup: campo expires_at fica preenchido pra job APScheduler limpar
relatorios velhos (>90d default). v1 do worker pode fazer cleanup no
mesmo tick do dry-run cleanup que ja existe.
"""

from alembic import op
import sqlalchemy as sa


revision = "bp002"
down_revision = "tax010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "base_processual_export",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_name", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDENTE",
        ),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_bytes", sa.Integer(), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_base_processual_export_status",
        "base_processual_export",
        ["status"],
    )
    op.create_index(
        "ix_base_processual_export_requested_at",
        "base_processual_export",
        ["requested_at"],
    )
    op.create_index(
        "ix_base_processual_export_template",
        "base_processual_export",
        ["template_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_base_processual_export_template",
        table_name="base_processual_export",
    )
    op.drop_index(
        "ix_base_processual_export_requested_at",
        table_name="base_processual_export",
    )
    op.drop_index(
        "ix_base_processual_export_status",
        table_name="base_processual_export",
    )
    op.drop_table("base_processual_export")
