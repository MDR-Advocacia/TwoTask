"""cla001: cria tabelas do modulo Classificador (diagnostico de carteira).

Revision ID: cla001
Revises: tax011
Create Date: 2026-05-12

4 tabelas novas:

- classificador_lote: cabecalho do diagnostico. 1 row por "carteira capturada"
  pelo operador. Agrega counts e totais desnormalizados (atualizados quando
  classificacao termina) pra dashboard nao precisar de agregacao N+1.

- classificador_processo: 1 row por processo da carteira. Espelha (snapshot)
  os dados de capa + patrocinio no momento da captura. source_intake_id e'
  FK opcional pra prazo_inicial_intakes — preserva rastreabilidade quando o
  processo veio do fluxo de Prazos Iniciais (com revisao humana previa),
  mas NAO bloqueia: o classificador roda sempre, com prompt proprio.
  ON DELETE SET NULL pra nao perder o snapshot se o intake original for
  deletado dos Prazos Iniciais.

- classificador_pedido: 1:N por processo. Mesma estrutura de prazo_inicial_pedidos
  (tipo, valores, prob. perda, aprovisionamento). Espelhado tambem.

- classificador_relatorio: 1 row por relatorio gerado (XLSX, PDF). Segue o
  padrao de base_processual_export — async com status PENDENTE/PROCESSANDO/
  PRONTO/FALHOU + file_path no volume.

Decisoes-chave (ver memory project_classificador.md):
- Snapshot, sempre. Relatorio e' documento historico imutavel.
- Refresh L1 ANTES do snapshot. Status do lote refletindo isso.
- source por PROCESSO (nao por LOTE) — permite misturar fontes no mesmo lote.
- Reclassifica sempre com classifier proprio do Classificador.
"""

from alembic import op
import sqlalchemy as sa


revision = "cla001"
down_revision = "tax011"
branch_labels = None
depends_on = None


# Status do lote (ciclo de vida do "diagnostico" inteiro).
LOTE_STATUS_RASCUNHO = "RASCUNHO"           # criado mas ainda nao iniciou
LOTE_STATUS_CAPTURANDO_L1 = "CAPTURANDO_L1"  # refresh L1 em curso
LOTE_STATUS_READY = "PRONTO_PARA_CLASSIFICAR"
LOTE_STATUS_CLASSIFYING = "CLASSIFICANDO"
LOTE_STATUS_CLASSIFIED = "CLASSIFICADO"
LOTE_STATUS_ERROR = "ERRO"
LOTE_STATUS_CANCELLED = "CANCELADO"

# Status do processo individual (granularidade pra retry isolado).
PROC_STATUS_PENDENTE = "PENDENTE"
PROC_STATUS_CAPTURANDO_L1 = "CAPTURANDO_L1"
PROC_STATUS_READY = "PRONTO_PARA_CLASSIFICAR"
PROC_STATUS_CLASSIFIED = "CLASSIFICADO"
PROC_STATUS_ERROR_CAPTURE = "ERRO_CAPTURA"
PROC_STATUS_ERROR_CLASSIFICATION = "ERRO_CLASSIFICACAO"

# Source por processo (nao por lote — permite mistura).
SOURCE_PRAZOS_INICIAIS = "PRAZOS_INICIAIS"
SOURCE_UPLOAD_XLSX = "UPLOAD_XLSX"
SOURCE_API_JSON = "API_JSON"

# Relatorio
REL_FORMAT_XLSX = "XLSX"
REL_FORMAT_PDF = "PDF"

REL_STATUS_PENDENTE = "PENDENTE"
REL_STATUS_PROCESSANDO = "PROCESSANDO"
REL_STATUS_PRONTO = "PRONTO"
REL_STATUS_FALHOU = "FALHOU"


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # classificador_lote: cabecalho do diagnostico
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        "classificador_lote",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("cliente_nome", sa.String(length=255), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=True),

        # Status do lote
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=LOTE_STATUS_RASCUNHO,
        ),

        # Composicao do lote (counts por fonte) + filtros aplicados
        # source_summary: {"PRAZOS_INICIAIS": 300, "UPLOAD_XLSX": 100}
        sa.Column("source_summary", sa.JSON(), nullable=True),
        # filtros_aplicados: payload original do POST /from-prazos-iniciais
        # (periodo, escritorio, status, cliente) — auditavel.
        sa.Column("filtros_aplicados", sa.JSON(), nullable=True),

        # Agregados desnormalizados (preenchidos quando classificacao termina)
        sa.Column("total_processos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_processos_capturados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_processos_classificados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_processos_com_erro", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valor_total_causa", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_total_estimado", sa.Numeric(18, 2), nullable=True),
        sa.Column("pcond_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("prob_exito_medio", sa.Numeric(5, 4), nullable=True),

        # Analise estrategica agregada do lote (gerada pela IA no fim — 1 call grande)
        sa.Column("analise_estrategica_carteira", sa.Text(), nullable=True),

        # Timestamps de cada fase (pra dashboard mostrar tempo gasto)
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("captura_l1_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captura_l1_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classificacao_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classificacao_finished_at", sa.DateTime(timezone=True), nullable=True),

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
    )
    op.create_index("ix_classificador_lote_status", "classificador_lote", ["status"])
    op.create_index("ix_classificador_lote_created_at", "classificador_lote", ["created_at"])
    op.create_index(
        "ix_classificador_lote_created_by",
        "classificador_lote",
        ["created_by_user_id"],
    )

    # ─────────────────────────────────────────────────────────────────
    # classificador_processo: snapshot por processo
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        "classificador_processo",
        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "lote_id",
            sa.Integer(),
            sa.ForeignKey("classificador_lote.id", ondelete="CASCADE"),
            nullable=False,
        ),

        # Source da linha — por processo, nao por lote (mistura ok)
        sa.Column("source", sa.String(length=32), nullable=False),
        # Rastreabilidade pro intake original (se source=PRAZOS_INICIAIS).
        # SET NULL permite preservar o snapshot mesmo se o intake for deletado.
        sa.Column(
            "source_intake_id",
            sa.Integer(),
            sa.ForeignKey("prazo_inicial_intakes.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # Identificacao do processo
        sa.Column("cnj_number", sa.String(length=64), nullable=True),
        sa.Column("lawsuit_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),

        # Capa (snapshot da L1 no momento data_captura_l1):
        # tribunal, vara, classe, assunto, valor_causa, data_distribuicao,
        # segredo_justica, situacao, andamentos_recentes (lista)
        sa.Column("capa_json", sa.JSON(), nullable=True),
        sa.Column("polo_ativo", sa.JSON(), nullable=True),
        sa.Column("polo_passivo", sa.JSON(), nullable=True),
        sa.Column("natureza_processo", sa.String(length=32), nullable=True),
        sa.Column("produto", sa.String(length=128), nullable=True),

        # Patrocinio (snapshot do calculo de _materialize_patrocinio):
        # decisao, escritorio_responsavel, advogado_responsavel, oab,
        # vinculada_master_nome, suspeita_devolucao, confianca, fundamentacao
        sa.Column("patrocinio_json", sa.JSON(), nullable=True),

        # Resultado do classifier do Classificador (taxonomy v2 + PCOND + prob_exito)
        sa.Column(
            "categoria_id",
            sa.Integer(),
            sa.ForeignKey("classification_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "subcategoria_id",
            sa.Integer(),
            sa.ForeignKey("classification_subcategories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("polo", sa.String(length=16), nullable=True),

        sa.Column("valor_estimado", sa.Numeric(18, 2), nullable=True),
        sa.Column("pcond_sugerido", sa.Numeric(18, 2), nullable=True),
        # 0.0 a 1.0
        sa.Column("prob_exito", sa.Numeric(5, 4), nullable=True),
        sa.Column("justificativa", sa.Text(), nullable=True),
        sa.Column("analise_estrategica", sa.Text(), nullable=True),
        # 0.0 a 1.0
        sa.Column("confianca", sa.Numeric(5, 4), nullable=True),

        # Status individual + erros
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=PROC_STATUS_PENDENTE,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),

        # Timestamps
        sa.Column("data_captura_l1", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_classificacao", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_classificador_processo_lote_id",
        "classificador_processo",
        ["lote_id"],
    )
    op.create_index(
        "ix_classificador_processo_cnj",
        "classificador_processo",
        ["cnj_number"],
    )
    op.create_index(
        "ix_classificador_processo_lote_status",
        "classificador_processo",
        ["lote_id", "status"],
    )
    op.create_index(
        "ix_classificador_processo_source_intake",
        "classificador_processo",
        ["source_intake_id"],
    )
    op.create_index(
        "ix_classificador_processo_categoria",
        "classificador_processo",
        ["categoria_id"],
    )

    # ─────────────────────────────────────────────────────────────────
    # classificador_pedido: 1:N com processo (espelho de prazo_inicial_pedidos)
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        "classificador_pedido",
        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "processo_id",
            sa.Integer(),
            sa.ForeignKey("classificador_processo.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column("tipo_pedido", sa.String(length=64), nullable=False),
        sa.Column("natureza", sa.String(length=64), nullable=True),
        sa.Column("valor_indicado", sa.Numeric(14, 2), nullable=True),
        sa.Column("valor_estimado", sa.Numeric(14, 2), nullable=True),
        sa.Column("fundamentacao_valor", sa.Text(), nullable=True),
        sa.Column("probabilidade_perda", sa.String(length=16), nullable=True),
        sa.Column("aprovisionamento", sa.Numeric(14, 2), nullable=True),
        sa.Column("fundamentacao_risco", sa.Text(), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),

        sa.CheckConstraint(
            "probabilidade_perda IS NULL OR probabilidade_perda IN ('remota', 'possivel', 'provavel')",
            name="ck_classificador_pedido_prob_perda",
        ),
    )
    op.create_index(
        "ix_classificador_pedido_processo",
        "classificador_pedido",
        ["processo_id"],
    )
    op.create_index(
        "ix_classificador_pedido_tipo",
        "classificador_pedido",
        ["tipo_pedido"],
    )

    # ─────────────────────────────────────────────────────────────────
    # classificador_relatorio: relatorios gerados (XLSX, PDF)
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        "classificador_relatorio",
        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "lote_id",
            sa.Integer(),
            sa.ForeignKey("classificador_lote.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column("formato", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=REL_STATUS_PENDENTE,
        ),

        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_bytes", sa.Integer(), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),

        # Parametros do relatorio (customizacoes futuras: filtros, secoes, etc.)
        sa.Column("params_json", sa.JSON(), nullable=True),
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

        sa.CheckConstraint(
            "formato IN ('XLSX', 'PDF')",
            name="ck_classificador_relatorio_formato",
        ),
    )
    op.create_index(
        "ix_classificador_relatorio_lote",
        "classificador_relatorio",
        ["lote_id"],
    )
    op.create_index(
        "ix_classificador_relatorio_status",
        "classificador_relatorio",
        ["status"],
    )
    op.create_index(
        "ix_classificador_relatorio_requested_at",
        "classificador_relatorio",
        ["requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classificador_relatorio_requested_at",
        table_name="classificador_relatorio",
    )
    op.drop_index(
        "ix_classificador_relatorio_status",
        table_name="classificador_relatorio",
    )
    op.drop_index(
        "ix_classificador_relatorio_lote",
        table_name="classificador_relatorio",
    )
    op.drop_table("classificador_relatorio")

    op.drop_index("ix_classificador_pedido_tipo", table_name="classificador_pedido")
    op.drop_index("ix_classificador_pedido_processo", table_name="classificador_pedido")
    op.drop_table("classificador_pedido")

    op.drop_index(
        "ix_classificador_processo_categoria",
        table_name="classificador_processo",
    )
    op.drop_index(
        "ix_classificador_processo_source_intake",
        table_name="classificador_processo",
    )
    op.drop_index(
        "ix_classificador_processo_lote_status",
        table_name="classificador_processo",
    )
    op.drop_index("ix_classificador_processo_cnj", table_name="classificador_processo")
    op.drop_index(
        "ix_classificador_processo_lote_id",
        table_name="classificador_processo",
    )
    op.drop_table("classificador_processo")

    op.drop_index("ix_classificador_lote_created_by", table_name="classificador_lote")
    op.drop_index("ix_classificador_lote_created_at", table_name="classificador_lote")
    op.drop_index("ix_classificador_lote_status", table_name="classificador_lote")
    op.drop_table("classificador_lote")
