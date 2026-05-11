"""bp001: cria tabelas do modulo Base Processual

Revision ID: bp001
Revises: pin023
Create Date: 2026-05-08

Tabelas (5):
- base_processual_upload: 1 row por upload (real, dry-run, idempotente ou falhou)
- base_processual_processo: estado atual por cod_ajus (chave natural do L1)
- base_processual_snapshot: payload normalizado + raw por (processo, upload)
- base_processual_evento: ENTROU / SAIU / ATUALIZADO / ATUALIZADO_MANUAL
- base_processual_api_key: chaves para consumidores externos

Indices criados pra suportar:
- lookup por cod_ajus / numero_processo / numero_pasta / numero_interno
- filtros compostos: (empresa, presenca_status), (uf, comarca),
  (empresa, usuario_responsavel)
- drill-down de eventos por upload + por processo cronologico
- idempotencia via file_sha256 UNIQUE
- api_key lookup por key_hash UNIQUE + revoked_at parcial

FK ciclica entre processo.current_snapshot_id e snapshot.processo_id e'
resolvida criando a coluna sem FK e adicionando o constraint depois com
op.create_foreign_key (use_alter).
"""

from alembic import op
import sqlalchemy as sa


revision = "bp001"
down_revision = "pin023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) base_processual_upload (independente — nenhuma FK out exceto users)
    op.create_table(
        "base_processual_upload",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        # NULL pra placeholders (IDEMPOTENTE/FAIL/DRY_RUN). UNIQUE permite
        # multiplos NULLs no PG, mantendo a constraint para shas reais.
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("file_bytes", sa.Integer(), nullable=True),
        sa.Column("total_rows_in_file", sa.Integer(), nullable=True),
        sa.Column("summary_novos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_removidos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_atualizados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_inalterados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDENTE",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("eventos_preview_json", sa.JSON(), nullable=True),
        sa.Column(
            "dry_run_of_upload_id",
            sa.Integer(),
            sa.ForeignKey(
                "base_processual_upload.id",
                ondelete="SET NULL",
                name="fk_bp_upload_dry_run_of_upload_id",
                use_alter=True,
            ),
            nullable=True,
        ),
        sa.Column("storage_path", sa.String(length=512), nullable=True),
        sa.Column(
            "uploaded_by_user_id",
            sa.Integer(),
            sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_base_processual_upload_status",
        "base_processual_upload",
        ["status"],
    )
    op.create_index(
        "ix_base_processual_upload_file_sha256",
        "base_processual_upload",
        ["file_sha256"],
        unique=True,
    )
    op.create_index(
        "ix_base_processual_upload_uploaded_at",
        "base_processual_upload",
        ["uploaded_at"],
    )

    # 2) base_processual_processo
    # current_snapshot_id e' criado SEM FK aqui — adicionado depois via create_foreign_key
    op.create_table(
        "base_processual_processo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cod_ajus", sa.String(length=64), nullable=False),
        sa.Column("numero_processo", sa.String(length=32), nullable=True),
        sa.Column("numero_processo_mascarado", sa.String(length=32), nullable=True),
        sa.Column("numero_interno", sa.String(length=128), nullable=True),
        sa.Column("numero_pasta", sa.String(length=128), nullable=True),
        sa.Column("acao_principal", sa.String(length=512), nullable=True),
        sa.Column("materia", sa.String(length=128), nullable=True),
        sa.Column("risco_prob_perda", sa.String(length=64), nullable=True),
        sa.Column("tipo_acao", sa.String(length=256), nullable=True),
        sa.Column("polo", sa.String(length=32), nullable=True),
        sa.Column("natureza", sa.String(length=64), nullable=True),
        sa.Column("numero_vara", sa.String(length=64), nullable=True),
        sa.Column("foro", sa.String(length=256), nullable=True),
        sa.Column("comarca", sa.String(length=128), nullable=True),
        sa.Column("uf", sa.String(length=2), nullable=True),
        sa.Column("empresa", sa.String(length=128), nullable=False),
        sa.Column("grupo_responsavel", sa.String(length=256), nullable=True),
        sa.Column("usuario_responsavel", sa.String(length=256), nullable=True),
        sa.Column("escritorio_responsavel", sa.String(length=256), nullable=True),
        sa.Column(
            "situacao_processo",
            sa.String(length=64),
            nullable=False,
            server_default="Ativo",
        ),
        sa.Column("justica_honorario", sa.String(length=128), nullable=True),
        sa.Column("valor_causa", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_prev_acordo", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_acordo", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_discutido", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_exito", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_condenacao", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_contingencia", sa.Numeric(18, 2), nullable=True),
        sa.Column("ult_andamento", sa.Text(), nullable=True),
        sa.Column("data_ult_andamento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dias_ult_atualizacao", sa.Integer(), nullable=True),
        sa.Column("distribuido_em", sa.Date(), nullable=True),
        sa.Column("processo_virtual", sa.Boolean(), nullable=True),
        sa.Column("numero_contrato", sa.String(length=128), nullable=True),
        sa.Column("usuario_cadastro_acao", sa.String(length=256), nullable=True),
        sa.Column("data_cadastro_acao", sa.DateTime(timezone=True), nullable=True),
        sa.Column("autores_raw", sa.Text(), nullable=True),
        sa.Column("reus_raw", sa.Text(), nullable=True),
        sa.Column("autores_json", sa.JSON(), nullable=True),
        sa.Column("reus_json", sa.JSON(), nullable=True),
        sa.Column(
            "presenca_status",
            sa.String(length=32),
            nullable=False,
            server_default="ATIVO_NA_BASE",
        ),
        sa.Column(
            "first_seen_upload_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_upload.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_seen_upload_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_upload.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "removed_at_upload_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_upload.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # current_snapshot_id sem FK aqui — adicionado depois (FK ciclica)
        sa.Column("current_snapshot_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_base_processual_processo_cod_ajus",
        "base_processual_processo",
        ["cod_ajus"],
        unique=True,
    )
    op.create_index(
        "ix_base_processual_processo_numero_processo",
        "base_processual_processo",
        ["numero_processo"],
    )
    op.create_index(
        "ix_base_processual_processo_numero_interno",
        "base_processual_processo",
        ["numero_interno"],
    )
    op.create_index(
        "ix_base_processual_processo_numero_pasta",
        "base_processual_processo",
        ["numero_pasta"],
    )
    op.create_index(
        "ix_base_processual_processo_materia",
        "base_processual_processo",
        ["materia"],
    )
    op.create_index(
        "ix_base_processual_processo_tipo_acao",
        "base_processual_processo",
        ["tipo_acao"],
    )
    op.create_index(
        "ix_base_processual_processo_polo",
        "base_processual_processo",
        ["polo"],
    )
    op.create_index(
        "ix_base_processual_processo_natureza",
        "base_processual_processo",
        ["natureza"],
    )
    op.create_index(
        "ix_base_processual_processo_comarca",
        "base_processual_processo",
        ["comarca"],
    )
    op.create_index(
        "ix_base_processual_processo_uf",
        "base_processual_processo",
        ["uf"],
    )
    op.create_index(
        "ix_base_processual_processo_empresa",
        "base_processual_processo",
        ["empresa"],
    )
    op.create_index(
        "ix_base_processual_processo_user",
        "base_processual_processo",
        ["usuario_responsavel"],
    )
    op.create_index(
        "ix_base_processual_processo_situacao",
        "base_processual_processo",
        ["situacao_processo"],
    )
    op.create_index(
        "ix_base_processual_processo_presenca",
        "base_processual_processo",
        ["presenca_status"],
    )
    op.create_index(
        "ix_base_processual_processo_emp_presenca",
        "base_processual_processo",
        ["empresa", "presenca_status"],
    )
    op.create_index(
        "ix_base_processual_processo_uf_comarca",
        "base_processual_processo",
        ["uf", "comarca"],
    )
    op.create_index(
        "ix_base_processual_processo_emp_user",
        "base_processual_processo",
        ["empresa", "usuario_responsavel"],
    )

    # 3) base_processual_snapshot
    op.create_table(
        "base_processual_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "processo_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_processo.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "upload_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_upload.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cod_ajus", sa.String(length=64), nullable=False),
        sa.Column("payload_normalized", sa.JSON(), nullable=False),
        sa.Column("payload_raw", sa.JSON(), nullable=True),
        sa.Column("diff_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "processo_id",
            "upload_id",
            name="uq_base_processual_snapshot_proc_upload",
        ),
    )
    op.create_index(
        "ix_base_processual_snapshot_processo",
        "base_processual_snapshot",
        ["processo_id"],
    )
    op.create_index(
        "ix_base_processual_snapshot_upload",
        "base_processual_snapshot",
        ["upload_id"],
    )
    op.create_index(
        "ix_base_processual_snapshot_cod_ajus",
        "base_processual_snapshot",
        ["cod_ajus"],
    )
    op.create_index(
        "ix_base_processual_snapshot_diff_hash",
        "base_processual_snapshot",
        ["diff_hash"],
    )
    op.create_index(
        "ix_base_processual_snapshot_proc_captured",
        "base_processual_snapshot",
        ["processo_id", "captured_at"],
    )

    # FK ciclica: processo.current_snapshot_id -> snapshot.id
    op.create_foreign_key(
        "fk_base_processual_processo_current_snapshot",
        "base_processual_processo",
        "base_processual_snapshot",
        ["current_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4) base_processual_evento
    op.create_table(
        "base_processual_evento",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "upload_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_upload.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processo_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_processo.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cod_ajus", sa.String(length=64), nullable=False),
        sa.Column("tipo_evento", sa.String(length=32), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=True),
        sa.Column(
            "snapshot_before_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_snapshot.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "snapshot_after_id",
            sa.Integer(),
            sa.ForeignKey("base_processual_snapshot.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_base_processual_evento_upload",
        "base_processual_evento",
        ["upload_id"],
    )
    op.create_index(
        "ix_base_processual_evento_processo",
        "base_processual_evento",
        ["processo_id"],
    )
    op.create_index(
        "ix_base_processual_evento_cod_ajus",
        "base_processual_evento",
        ["cod_ajus"],
    )
    op.create_index(
        "ix_base_processual_evento_tipo",
        "base_processual_evento",
        ["tipo_evento"],
    )
    op.create_index(
        "ix_base_processual_evento_created",
        "base_processual_evento",
        ["created_at"],
    )
    op.create_index(
        "ix_base_processual_evento_upload_tipo",
        "base_processual_evento",
        ["upload_id", "tipo_evento"],
    )
    op.create_index(
        "ix_base_processual_evento_proc_created",
        "base_processual_evento",
        ["processo_id", "created_at"],
    )

    # 5) base_processual_api_key
    op.create_table(
        "base_processual_api_key",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=256), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column(
            "scope",
            sa.String(length=64),
            nullable=False,
            server_default="read_processos",
        ),
        sa.Column(
            "rate_limit_per_min",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_base_processual_api_key_hash",
        "base_processual_api_key",
        ["key_hash"],
        unique=True,
    )
    op.create_index(
        "ix_base_processual_api_key_revoked",
        "base_processual_api_key",
        ["revoked_at"],
    )


def downgrade() -> None:
    # ordem reversa: api_key, evento, depois FK ciclica, snapshot, processo, upload
    op.drop_index("ix_base_processual_api_key_revoked", table_name="base_processual_api_key")
    op.drop_index("ix_base_processual_api_key_hash", table_name="base_processual_api_key")
    op.drop_table("base_processual_api_key")

    op.drop_index("ix_base_processual_evento_proc_created", table_name="base_processual_evento")
    op.drop_index("ix_base_processual_evento_upload_tipo", table_name="base_processual_evento")
    op.drop_index("ix_base_processual_evento_created", table_name="base_processual_evento")
    op.drop_index("ix_base_processual_evento_tipo", table_name="base_processual_evento")
    op.drop_index("ix_base_processual_evento_cod_ajus", table_name="base_processual_evento")
    op.drop_index("ix_base_processual_evento_processo", table_name="base_processual_evento")
    op.drop_index("ix_base_processual_evento_upload", table_name="base_processual_evento")
    op.drop_table("base_processual_evento")

    op.drop_constraint(
        "fk_base_processual_processo_current_snapshot",
        "base_processual_processo",
        type_="foreignkey",
    )

    op.drop_index("ix_base_processual_snapshot_proc_captured", table_name="base_processual_snapshot")
    op.drop_index("ix_base_processual_snapshot_diff_hash", table_name="base_processual_snapshot")
    op.drop_index("ix_base_processual_snapshot_cod_ajus", table_name="base_processual_snapshot")
    op.drop_index("ix_base_processual_snapshot_upload", table_name="base_processual_snapshot")
    op.drop_index("ix_base_processual_snapshot_processo", table_name="base_processual_snapshot")
    op.drop_table("base_processual_snapshot")

    op.drop_index("ix_base_processual_processo_emp_user", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_uf_comarca", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_emp_presenca", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_presenca", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_situacao", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_user", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_empresa", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_uf", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_comarca", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_natureza", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_polo", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_tipo_acao", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_materia", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_numero_pasta", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_numero_interno", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_numero_processo", table_name="base_processual_processo")
    op.drop_index("ix_base_processual_processo_cod_ajus", table_name="base_processual_processo")
    op.drop_table("base_processual_processo")

    op.drop_index("ix_base_processual_upload_uploaded_at", table_name="base_processual_upload")
    op.drop_index("ix_base_processual_upload_file_sha256", table_name="base_processual_upload")
    op.drop_index("ix_base_processual_upload_status", table_name="base_processual_upload")
    op.drop_table("base_processual_upload")
