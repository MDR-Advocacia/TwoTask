"""adiciona source/submitted_by/extractor/habilitacao_pdf no intake

Suporta dois fluxos de origem de intake:
- EXTERNAL_API: provedor externo (PJe scraper) via X-Intake-Api-Key — modo
  histórico, único existente até aqui. Backfill default.
- USER_UPLOAD: operador sobe o PDF do processo na íntegra direto pela UI;
  motor de extração (pdfplumber + extractor PJe TJBA) monta capa+integra
  mecanicamente. PDF do processo é descartado após extração ok pra
  economizar disco; se a extração falhar, mantém o PDF e marca
  pdf_extraction_failed pra UI exibir "classificar manualmente".

Habilitação MDR (procuração + carta de preposição) é PDF separado que
acompanha o upload — preservado em habilitacao_pdf_path porque vai pro
GED L1 e AJUS (memory project_pin_habilitacao_ajus.md).

Revision ID: pin016
Revises: pin015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "pin016"
down_revision: Union[str, None] = "pin015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="EXTERNAL_API",
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("source_provider_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("submitted_by_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("submitted_by_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "pdf_extraction_failed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("extractor_used", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("extraction_confidence", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("habilitacao_pdf_path", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("habilitacao_pdf_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column("habilitacao_pdf_bytes", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "habilitacao_pdf_filename_original",
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_prazo_inicial_intakes_source",
        "prazo_inicial_intakes",
        ["source"],
    )
    op.create_index(
        "ix_prazo_inicial_intakes_submitted_by_user_id",
        "prazo_inicial_intakes",
        ["submitted_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prazo_inicial_intakes_submitted_by_user_id",
        table_name="prazo_inicial_intakes",
    )
    op.drop_index(
        "ix_prazo_inicial_intakes_source",
        table_name="prazo_inicial_intakes",
    )
    op.drop_column("prazo_inicial_intakes", "habilitacao_pdf_filename_original")
    op.drop_column("prazo_inicial_intakes", "habilitacao_pdf_bytes")
    op.drop_column("prazo_inicial_intakes", "habilitacao_pdf_sha256")
    op.drop_column("prazo_inicial_intakes", "habilitacao_pdf_path")
    op.drop_column("prazo_inicial_intakes", "extraction_confidence")
    op.drop_column("prazo_inicial_intakes", "extractor_used")
    op.drop_column("prazo_inicial_intakes", "pdf_extraction_failed")
    op.drop_column("prazo_inicial_intakes", "submitted_at")
    op.drop_column("prazo_inicial_intakes", "submitted_by_name")
    op.drop_column("prazo_inicial_intakes", "submitted_by_email")
    op.drop_column("prazo_inicial_intakes", "submitted_by_user_id")
    op.drop_column("prazo_inicial_intakes", "source_provider_name")
    op.drop_column("prazo_inicial_intakes", "source")
