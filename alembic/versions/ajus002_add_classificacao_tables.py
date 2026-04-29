"""Adiciona tabelas do módulo de classificação AJUS (Chunk 1).

Modulo paralelo ao de andamentos: classifica processos na CAPA do AJUS
via RPA Playwright (porte do Mirror). O cliente do MDR exige que a
pasta esteja classificada (Matéria + Justiça/Honorário + Risco) pra
que o andamento provoque remuneração ao escritório. O Mirror já fazia
isso com 100% de sucesso na classificação — só engasgava na inserção
do andamento (que agora vai via API REST AJUS, no módulo
`ajus_andamento_queue`).

Tabelas:
- `ajus_classificacao_defaults`: singleton (id=1) com matter/risco
  default usados quando intake é enfileirado automaticamente.
- `ajus_classificacao_queue`: fila de processos a classificar. 2
  origens — `intake_auto` (criado quando intake recebe status
  RECEBIDO) e `planilha` (operador sobe XLSX com tudo preenchido).

Revision ID: ajus002
Revises: ajus001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus002"
down_revision: Union[str, None] = "ajus001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Defaults globais (singleton) ─────────────────────────────────
    op.create_table(
        "ajus_classificacao_defaults",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("default_matter", sa.String(length=255), nullable=True),
        sa.Column(
            "default_risk_loss_probability",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_ajus_classif_defaults_singleton"),
    )

    # ── Fila de classificação de processos no AJUS ───────────────────
    op.create_table(
        "ajus_classificacao_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cnj_number", sa.String(length=25), nullable=False, unique=True),
        sa.Column(
            "intake_id",
            sa.Integer(),
            sa.ForeignKey("prazo_inicial_intakes.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # `intake_auto` (criado pelo hook do intake_service) ou
        # `planilha` (upload XLSX). Permite filtros e auditoria.
        sa.Column(
            "origem",
            sa.String(length=16),
            nullable=False,
            index=True,
        ),
        # Os 5 campos que o Mirror preenche na capa do processo no AJUS.
        # `uf` é sempre derivada do CNJ (via uf_from_cnj). `comarca` vem
        # do intake (Jurisdição -> fallback vara) ou da planilha. Os
        # outros 3 vêm dos defaults (auto) ou da planilha (manual).
        sa.Column("uf", sa.String(length=8), nullable=True),
        sa.Column("comarca", sa.String(length=255), nullable=True),
        sa.Column("matter", sa.String(length=255), nullable=True),
        sa.Column("justice_fee", sa.String(length=255), nullable=True),
        sa.Column(
            "risk_loss_probability", sa.String(length=255), nullable=True,
        ),
        # Status do processamento via runner Playwright (Chunk 2):
        #   pendente   — aguardando dispatch
        #   processando — runner abriu o processo no AJUS
        #   sucesso    — capa atualizada e validada
        #   erro       — falha no Playwright (vide error_message)
        #   cancelado  — operador cancelou manualmente
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pendente",
            index=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Log do runner: progress steps + capturas de DOM/screenshots
        # (caminho relativo). Útil pra debug. Texto livre.
        sa.Column("last_log", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origem IN ('intake_auto','planilha')",
            name="ck_ajus_classif_queue_origem",
        ),
        sa.CheckConstraint(
            "status IN ('pendente','processando','sucesso','erro','cancelado')",
            name="ck_ajus_classif_queue_status",
        ),
    )


    # Seed do singleton de defaults (id=1, valores nulos — admin edita
    # pela UI antes do primeiro intake_auto começar a popular a fila).
    op.execute(
        "INSERT INTO ajus_classificacao_defaults (id) VALUES (1) "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("ajus_classificacao_queue")
    op.drop_table("ajus_classificacao_defaults")
