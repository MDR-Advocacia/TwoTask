"""Minha Equipe (Performance de Equipes): perf_pessoa, perf_l1_tarefa, perf_subtipo_categoria

Revision ID: perf001_minha_equipe
Revises: onr004_proc_l1_check
Create Date: 2026-06-26

Fundação do módulo "Minha Equipe" — dashboard de desempenho por pessoa a partir
das tarefas do Legal One. Três tabelas (prefixo perf*):

- perf_pessoa            — roster: nome, cargo, squad, posição (importado da
                          planilha de squads; editável depois no admin).
- perf_l1_tarefa         — uma linha por tarefa do L1 (seed do export agora,
                          API /Tasks incremental depois). pessoa_id resolve o
                          executor (Cumprido) ou o responsável (Pendente).
- perf_subtipo_categoria — classificação de cada subtipo em
                          operacional/profundo/ruído (auto no seed, ajuste
                          manual depois). Define qual métrica vale por tipo.

Idempotente (guard por has_table) — seguro reaplicar no boot do Coolify.
"""

from alembic import op
import sqlalchemy as sa


revision = "perf001_minha_equipe"
down_revision = "onr004_proc_l1_check"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if not _has_table("perf_pessoa"):
        op.create_table(
            "perf_pessoa",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nome", sa.String(), nullable=False),
            sa.Column("nome_norm", sa.String(), nullable=False),
            sa.Column("cargo", sa.String(), nullable=True),
            sa.Column("squad", sa.String(), nullable=True),
            sa.Column("posicao", sa.String(), nullable=True),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_perf_pessoa_nome_norm", "perf_pessoa", ["nome_norm"], unique=True)

    if not _has_table("perf_l1_tarefa"):
        op.create_table(
            "perf_l1_tarefa",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("l1_task_id", sa.BigInteger(), nullable=True),
            sa.Column("pessoa_id", sa.Integer(), sa.ForeignKey("perf_pessoa.id"), nullable=True),
            sa.Column("cumprido_por_nome", sa.String(), nullable=True),
            sa.Column("envolvido_nome", sa.String(), nullable=True),
            sa.Column("escritorio", sa.String(), nullable=True),
            sa.Column("tipo", sa.String(), nullable=True),
            sa.Column("subtipo", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("cadastrado_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("concluido_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("prazo_previsto", sa.DateTime(timezone=True), nullable=True),
            sa.Column("pasta", sa.String(), nullable=True),
            sa.Column("cnj", sa.String(), nullable=True),
            sa.Column("uf", sa.String(), nullable=True),
            sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_perf_tarefa_pessoa", "perf_l1_tarefa", ["pessoa_id"])
        op.create_index("ix_perf_tarefa_concluido", "perf_l1_tarefa", ["concluido_em"])
        op.create_index("ix_perf_tarefa_subtipo", "perf_l1_tarefa", ["subtipo"])
        op.create_index("ix_perf_tarefa_status", "perf_l1_tarefa", ["status"])

    if not _has_table("perf_subtipo_categoria"):
        op.create_table(
            "perf_subtipo_categoria",
            sa.Column("subtipo", sa.String(), primary_key=True),
            sa.Column("categoria", sa.String(), nullable=False, server_default="profundo"),
            sa.Column("volume", sa.Integer(), nullable=True),
            sa.Column("densidade", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    for t in ("perf_l1_tarefa", "perf_subtipo_categoria", "perf_pessoa"):
        if _has_table(t):
            op.drop_table(t)
