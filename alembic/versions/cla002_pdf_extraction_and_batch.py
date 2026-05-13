"""cla002: tabela classificador_batch + colunas PDF/integra/extractor em classificador_processo.

Revision ID: cla002
Revises: cla001
Create Date: 2026-05-12

Espelha o pattern do PI (prazo_inicial_intake/batch) pra o modulo
Classificador poder reaproveitar o pipeline:

  PDF chega -> pdf_extractor (mecanico, do PI) -> capa_json + integra_json
            -> sanitizer (do PI) -> reduz tokens
            -> Anthropic Batches API (Sonnet) -> classificacao
            -> apply_batch_results -> popula campos do processo

1 tabela nova:
- classificador_batch: rastreabilidade do batch Anthropic (ID, status,
  contadores succeeded/errored/expired/canceled, results_url, modelo).
  1 row por submit. Multiplos batches por lote (re-run, retry).

Colunas novas em classificador_processo:
- pdf_path, pdf_sha256, pdf_bytes, pdf_filename_original — storage
- integra_json — saida do pdf_extractor (timeline com docs estruturados)
- metadata_json — livre (origem, etc.)
- pdf_extraction_failed — boolean (PDF sem texto / corrompido)
- extractor_used — string (pje_v1 / eproc_v1 / fallback_text / etc.)
- extraction_confidence — high / partial / low
- classification_batch_id — FK pra classificador_batch (SET NULL)
- classificacao_response_json — resposta CRUA da IA persistida
  (inclui sentenca + transito_julgado + primeira_habilitacao_master +
   contestacao_existente — campos pedidos pelo operador alem dos do PI)
- contestacao_existente_json — espelho do PI, materializado tambem
  no nivel do processo pra query rapida no relatorio
"""

from alembic import op
import sqlalchemy as sa


revision = "cla002"
down_revision = "cla001"
branch_labels = None
depends_on = None


# Status do batch (espelhado do PI: PIN_BATCH_STATUS_*)
BATCH_STATUS_SUBMITTED = "ENVIADO"
BATCH_STATUS_IN_PROGRESS = "EM_PROCESSAMENTO"
BATCH_STATUS_READY = "PRONTO"
BATCH_STATUS_APPLIED = "APLICADO"
BATCH_STATUS_FAILED = "FALHA"
BATCH_STATUS_CANCELLED = "CANCELADO"


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # classificador_batch
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        "classificador_batch",
        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "lote_id",
            sa.Integer(),
            sa.ForeignKey("classificador_lote.id", ondelete="CASCADE"),
            nullable=False,
        ),

        # ID retornado pela Anthropic na submissao
        sa.Column("anthropic_batch_id", sa.String(length=128), nullable=True),
        sa.Column("anthropic_status", sa.String(length=32), nullable=True),

        # Status local (controle do nosso lado)
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=BATCH_STATUS_SUBMITTED,
        ),

        # Lista de processo_ids incluidos no batch (JSON array de ints)
        sa.Column("processo_ids", sa.JSON(), nullable=True),

        # Mapeamento custom_id (string) -> processo_id (int) pra
        # apply_batch_results conseguir parsear o JSONL de volta
        sa.Column("batch_metadata", sa.JSON(), nullable=True),

        sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("canceled_count", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("model_used", sa.String(length=128), nullable=True),
        sa.Column("results_url", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),

        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("requested_by_email", sa.String(length=255), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_classificador_batch_lote",
        "classificador_batch",
        ["lote_id"],
    )
    op.create_index(
        "ix_classificador_batch_status",
        "classificador_batch",
        ["status"],
    )
    op.create_index(
        "ix_classificador_batch_anthropic_id",
        "classificador_batch",
        ["anthropic_batch_id"],
    )

    # ─────────────────────────────────────────────────────────────────
    # Novas colunas em classificador_processo
    # ─────────────────────────────────────────────────────────────────
    op.add_column(
        "classificador_processo",
        sa.Column("pdf_path", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "classificador_processo",
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "classificador_processo",
        sa.Column("pdf_bytes", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "classificador_processo",
        sa.Column("pdf_filename_original", sa.String(length=255), nullable=True),
    )

    op.add_column(
        "classificador_processo",
        sa.Column("integra_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "classificador_processo",
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )

    op.add_column(
        "classificador_processo",
        sa.Column(
            "pdf_extraction_failed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "classificador_processo",
        sa.Column("extractor_used", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "classificador_processo",
        sa.Column("extraction_confidence", sa.String(length=16), nullable=True),
    )

    # FK pra batch corrente (NULL ate' classificar)
    op.add_column(
        "classificador_processo",
        sa.Column(
            "classification_batch_id",
            sa.Integer(),
            sa.ForeignKey("classificador_batch.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Resposta CRUA da IA — guardada inteira pra auditoria + permite
    # rerodar materializacao sem chamar batch de novo se mudar schema
    op.add_column(
        "classificador_processo",
        sa.Column("classificacao_response_json", sa.JSON(), nullable=True),
    )

    # Contestacao existente (espelho do PI, materializado pra relatorio)
    op.add_column(
        "classificador_processo",
        sa.Column("contestacao_existente_json", sa.JSON(), nullable=True),
    )

    # Indices uteis pra filtragem
    op.create_index(
        "ix_classificador_processo_pdf_sha256",
        "classificador_processo",
        ["pdf_sha256"],
    )
    op.create_index(
        "ix_classificador_processo_batch",
        "classificador_processo",
        ["classification_batch_id"],
    )
    op.create_index(
        "ix_classificador_processo_extractor",
        "classificador_processo",
        ["extractor_used"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classificador_processo_extractor",
        table_name="classificador_processo",
    )
    op.drop_index(
        "ix_classificador_processo_batch",
        table_name="classificador_processo",
    )
    op.drop_index(
        "ix_classificador_processo_pdf_sha256",
        table_name="classificador_processo",
    )

    op.drop_column("classificador_processo", "contestacao_existente_json")
    op.drop_column("classificador_processo", "classificacao_response_json")
    op.drop_column("classificador_processo", "classification_batch_id")
    op.drop_column("classificador_processo", "extraction_confidence")
    op.drop_column("classificador_processo", "extractor_used")
    op.drop_column("classificador_processo", "pdf_extraction_failed")
    op.drop_column("classificador_processo", "metadata_json")
    op.drop_column("classificador_processo", "integra_json")
    op.drop_column("classificador_processo", "pdf_filename_original")
    op.drop_column("classificador_processo", "pdf_bytes")
    op.drop_column("classificador_processo", "pdf_sha256")
    op.drop_column("classificador_processo", "pdf_path")

    op.drop_index(
        "ix_classificador_batch_anthropic_id",
        table_name="classificador_batch",
    )
    op.drop_index(
        "ix_classificador_batch_status",
        table_name="classificador_batch",
    )
    op.drop_index(
        "ix_classificador_batch_lote",
        table_name="classificador_batch",
    )
    op.drop_table("classificador_batch")
