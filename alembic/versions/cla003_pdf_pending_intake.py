"""cla003: tabela classificador_pdf_pending — fila de PDFs do intake automatico.

Revision ID: cla003
Revises: cla002
Create Date: 2026-05-13

Tabela que recebe PDFs do robo de entrega (API externa) e fica
dormente ate o worker `pending_worker` agrupar em batches de 50 por
cliente e criar lotes automaticamente.

Fluxo:
1. Robo POST /classificador/intake/pdf (multipart + X-Classificador-Api-Key)
2. PDF salvo no volume + row em classificador_pdf_pending status=PENDENTE
3. Worker tick (60s): agrupa por cliente_nome, quando atinge 50 OU
   passa do timeout (30min) → cria lote + move pra ALOCADO + ingest_pdf
   + status=PROCESSADO. Se tudo OK, dispara classify do lote.
4. Lote aparece no Historico do operador (status=CAPTURANDO_L1 -> CLASSIFICADO).

Status do pending:
- PENDENTE: aguardando worker agrupar
- ALOCADO: worker amarrou a um lote, ingest_pdf em curso
- PROCESSADO: ingest_pdf OK, processo criado e amarrado
- ERRO: falha (PDF invalido, etc.)
"""

from alembic import op
import sqlalchemy as sa


revision = "cla003"
down_revision = "cla002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classificador_pdf_pending",
        sa.Column("id", sa.Integer(), primary_key=True),

        # Storage do PDF (salvo via prazos_iniciais.storage.save_pdf)
        sa.Column("pdf_path", sa.String(length=512), nullable=False),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=False),
        sa.Column("pdf_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pdf_filename_original", sa.String(length=255), nullable=True),

        # Metadata do request (do robo)
        sa.Column("cliente_nome", sa.String(length=255), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("cnj_hint", sa.String(length=64), nullable=True),
        sa.Column("produto", sa.String(length=128), nullable=True),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),

        # Estado da fila
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDENTE",
        ),
        sa.Column(
            "lote_id",
            sa.Integer(),
            sa.ForeignKey("classificador_lote.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("processo_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),

        # Timestamps
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("allocated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_classificador_pdf_pending_status",
        "classificador_pdf_pending",
        ["status"],
    )
    op.create_index(
        "ix_classificador_pdf_pending_cliente",
        "classificador_pdf_pending",
        ["cliente_nome"],
    )
    op.create_index(
        "ix_classificador_pdf_pending_received",
        "classificador_pdf_pending",
        ["received_at"],
    )
    op.create_index(
        "ix_classificador_pdf_pending_lote",
        "classificador_pdf_pending",
        ["lote_id"],
    )
    op.create_index(
        "ix_classificador_pdf_pending_sha256",
        "classificador_pdf_pending",
        ["pdf_sha256"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classificador_pdf_pending_sha256",
        table_name="classificador_pdf_pending",
    )
    op.drop_index(
        "ix_classificador_pdf_pending_lote",
        table_name="classificador_pdf_pending",
    )
    op.drop_index(
        "ix_classificador_pdf_pending_received",
        table_name="classificador_pdf_pending",
    )
    op.drop_index(
        "ix_classificador_pdf_pending_cliente",
        table_name="classificador_pdf_pending",
    )
    op.drop_index(
        "ix_classificador_pdf_pending_status",
        table_name="classificador_pdf_pending",
    )
    op.drop_table("classificador_pdf_pending")
