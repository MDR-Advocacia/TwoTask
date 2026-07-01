"""Análise Recursal: análises, batches e tabela de custas por estado

Revision ID: rcr001_analise_recursal
Revises: perf009_cancel_massa
Create Date: 2026-06-30

Módulo novo dentro de Prazos Processuais. Operador sobe PDF do processo
(nomeado pelo número do processo); reusa o extractor mecânico de Prazos
Iniciais + 1 chamada Sonnet (Batches) → veredito de viabilidade recursal.
Custo do preparo é determinístico (lookup em recursal_custas, alimentada
pelo operador). Idempotente.
"""

from alembic import op
import sqlalchemy as sa


revision = "rcr001_analise_recursal"
down_revision = "perf009_cancel_massa"
branch_labels = None
depends_on = None


def _has_table(t: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(t)


def upgrade() -> None:
    # 1. Batches (criado antes da análise por causa da FK).
    if not _has_table("analise_recursal_batches"):
        op.create_table(
            "analise_recursal_batches",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("anthropic_batch_id", sa.String(), nullable=True, index=True),
            sa.Column("status", sa.String(), nullable=False, server_default="ENVIADO", index=True),
            sa.Column("anthropic_status", sa.String(), nullable=True),
            sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("succeeded_count", sa.Integer(), server_default="0"),
            sa.Column("errored_count", sa.Integer(), server_default="0"),
            sa.Column("expired_count", sa.Integer(), server_default="0"),
            sa.Column("canceled_count", sa.Integer(), server_default="0"),
            sa.Column("analise_ids", sa.JSON(), nullable=True),
            sa.Column("batch_metadata", sa.JSON(), nullable=True),
            sa.Column("model_used", sa.String(), nullable=True),
            sa.Column("requested_by_email", sa.String(), nullable=True, index=True),
            sa.Column("results_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 2. Análises.
    if not _has_table("analise_recursal"):
        op.create_table(
            "analise_recursal",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("processo_numero", sa.String(), nullable=False, index=True),
            sa.Column("cnj_number", sa.String(), nullable=True, index=True),
            sa.Column("uf", sa.String(), nullable=True, index=True),
            sa.Column("capa_json", sa.JSON(), nullable=True),
            sa.Column("integra_json", sa.JSON(), nullable=True),
            sa.Column("extractor_used", sa.String(), nullable=True),
            sa.Column("extraction_confidence", sa.String(), nullable=True),
            sa.Column("extraction_failed", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("pdf_sha256", sa.String(), nullable=True, index=True),
            sa.Column("pdf_filename_original", sa.String(), nullable=True),
            sa.Column("pdf_bytes", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="RECEBIDO", index=True),
            sa.Column(
                "analysis_batch_id",
                sa.Integer(),
                sa.ForeignKey("analise_recursal_batches.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            # identificação (cabeçalho do parecer)
            sa.Column("nome_autor", sa.String(), nullable=True),
            sa.Column("cpf", sa.String(), nullable=True),
            sa.Column("objeto", sa.String(), nullable=True),
            sa.Column("produto", sa.String(), nullable=True),
            sa.Column("tribunal", sa.String(), nullable=True),
            # veredito + conteúdo do parecer
            sa.Column("resultado_decisao", sa.String(), nullable=True),
            sa.Column("tipo_decisao", sa.String(), nullable=True),
            sa.Column("resumo_topicos", sa.JSON(), nullable=True),
            sa.Column("destaque", sa.Text(), nullable=True),
            sa.Column("fundamentacao_juiz", sa.Text(), nullable=True),
            sa.Column("pontos_analise", sa.JSON(), nullable=True),
            sa.Column("probabilidade_reversao", sa.String(), nullable=True),
            sa.Column("recorrer", sa.String(), nullable=True),
            sa.Column("tipo_recurso", sa.String(), nullable=True),
            sa.Column("fundamentacao", sa.Text(), nullable=True),
            sa.Column("valor_causa", sa.Numeric(14, 2), nullable=True),
            sa.Column("valor_condenacao", sa.String(), nullable=True),
            sa.Column("prazo_fatal", sa.Date(), nullable=True),
            sa.Column("custo_estimado", sa.Numeric(14, 2), nullable=True),
            sa.Column("custo_detalhe", sa.JSON(), nullable=True),
            sa.Column("confianca", sa.String(), nullable=True),
            sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
            sa.Column("uploaded_by_email", sa.String(), nullable=True, index=True),
            sa.Column("uploaded_by_name", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 3. Tabela de custas por UF × tipo de recurso (alimentada pelo operador).
    if not _has_table("recursal_custas"):
        op.create_table(
            "recursal_custas",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("uf", sa.String(), nullable=False, index=True),
            sa.Column("tribunal", sa.String(), nullable=True),
            sa.Column("tipo_recurso", sa.String(), nullable=False, index=True),
            sa.Column("percentual", sa.Numeric(7, 4), nullable=False, server_default="0"),
            sa.Column("valor_fixo", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("valor_minimo", sa.Numeric(14, 2), nullable=True),
            sa.Column("valor_maximo", sa.Numeric(14, 2), nullable=True),
            sa.Column("porte_remessa_retorno", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("vigencia", sa.String(), nullable=True),
            sa.Column("fundamentacao", sa.Text(), nullable=True),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default="true", index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    for t in ("analise_recursal", "recursal_custas", "analise_recursal_batches"):
        if _has_table(t):
            op.drop_table(t)
