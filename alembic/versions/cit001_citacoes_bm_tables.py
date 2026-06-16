"""cit001: tabelas do modulo Citacoes BM (monitoramento de citacao via DataJud).

Revision ID: cit001
Revises: sso002
Create Date: 2026-06-16

Cria 2 tabelas pro monitoramento de citacao do Banco Master (Reu):

- cit_processos: 1 linha por CNJ monitorado. Status de citacao alterado
  EXCLUSIVAMENTE pelo operador; monitoramento_ativo vira False ao marcar
  CITADO (arquiva). Contadores denormalizados (total/novos movimentos,
  tem_candidato) pra a listagem nao precisar agregar por processo.
- cit_movimentos: movimentacoes capturadas do DataJud. fingerprint unico
  por processo (dedupe). is_candidato_citacao destaca candidatos; lido
  marca o que e' novo desde a ultima visita do operador.

head atual = sso002 (conferido via `alembic heads` no container
onetask-api-1, branch main). Single head, sem merge necessario.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "cit001"
down_revision = "sso002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cit_processos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cnj", sa.String(25), nullable=False),
        sa.Column("cnj_mask", sa.String(40), nullable=True),
        sa.Column("lawsuit_id", sa.Integer(), nullable=True),
        sa.Column("office_external_id", sa.Integer(), nullable=True),
        sa.Column("office_path", sa.String(), nullable=True),
        sa.Column("l1_creation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tribunal_alias", sa.String(40), nullable=True),
        sa.Column("uf", sa.String(4), nullable=True),
        sa.Column("cidade", sa.String(), nullable=True),
        sa.Column("acao", sa.String(), nullable=True),
        sa.Column("cliente", sa.String(), nullable=True),
        sa.Column("contrario", sa.String(), nullable=True),
        sa.Column(
            "origem", sa.String(16), nullable=False, server_default="LISTA_MANUAL"
        ),
        sa.Column(
            "status_citacao",
            sa.String(16),
            nullable=False,
            server_default="PENDENTE",
        ),
        sa.Column("citado_por_user_id", sa.Integer(), nullable=True),
        sa.Column("citado_por_nome", sa.String(), nullable=True),
        sa.Column("citado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column(
            "monitoramento_ativo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scan_status", sa.String(16), nullable=True),
        sa.Column("last_scan_error", sa.Text(), nullable=True),
        sa.Column("last_movement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "total_movimentos", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "novos_movimentos", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "tem_candidato_citacao",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_by_email", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_cit_processos_cnj", "cit_processos", ["cnj"], unique=True
    )
    op.create_index("ix_cit_processos_lawsuit_id", "cit_processos", ["lawsuit_id"])
    op.create_index(
        "ix_cit_processos_office_external_id",
        "cit_processos",
        ["office_external_id"],
    )
    op.create_index(
        "ix_cit_processos_status_citacao", "cit_processos", ["status_citacao"]
    )
    op.create_index(
        "ix_cit_processos_monitoramento_ativo",
        "cit_processos",
        ["monitoramento_ativo"],
    )

    op.create_table(
        "cit_movimentos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "processo_id",
            sa.Integer(),
            sa.ForeignKey("cit_processos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("codigo_tpu", sa.Integer(), nullable=True),
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("grau", sa.String(8), nullable=True),
        sa.Column("data_hora", sa.DateTime(timezone=True), nullable=True),
        sa.Column("complementos", postgresql.JSONB(), nullable=True),
        sa.Column("orgao_julgador", sa.String(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "is_candidato_citacao",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("cit_match_termo", sa.String(), nullable=True),
        sa.Column("lido", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("processo_id", "fingerprint", name="uq_cit_mov_fp"),
    )
    op.create_index(
        "ix_cit_movimentos_processo_id", "cit_movimentos", ["processo_id"]
    )
    op.create_index(
        "ix_cit_movimentos_data_hora", "cit_movimentos", ["data_hora"]
    )
    op.create_index(
        "ix_cit_movimentos_fingerprint", "cit_movimentos", ["fingerprint"]
    )
    op.create_index(
        "ix_cit_movimentos_is_candidato_citacao",
        "cit_movimentos",
        ["is_candidato_citacao"],
    )
    op.create_index("ix_cit_movimentos_lido", "cit_movimentos", ["lido"])


def downgrade() -> None:
    op.drop_index("ix_cit_movimentos_lido", "cit_movimentos")
    op.drop_index("ix_cit_movimentos_is_candidato_citacao", "cit_movimentos")
    op.drop_index("ix_cit_movimentos_fingerprint", "cit_movimentos")
    op.drop_index("ix_cit_movimentos_data_hora", "cit_movimentos")
    op.drop_index("ix_cit_movimentos_processo_id", "cit_movimentos")
    op.drop_table("cit_movimentos")

    op.drop_index("ix_cit_processos_monitoramento_ativo", "cit_processos")
    op.drop_index("ix_cit_processos_status_citacao", "cit_processos")
    op.drop_index("ix_cit_processos_office_external_id", "cit_processos")
    op.drop_index("ix_cit_processos_lawsuit_id", "cit_processos")
    op.drop_index("ix_cit_processos_cnj", "cit_processos")
    op.drop_table("cit_processos")
