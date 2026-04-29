"""Adiciona tabela de contas de sessão AJUS (multi-conta) — Chunk 2a.

Backlog grande (~2.300 + 200/dia) e sessões AJUS têm fragilidades
(expiram, pedem IP-code, podem brigar com uso humano), então o módulo
suporta N contas em paralelo desde o início. Cada conta tem seu
storage_state.json isolado, próprio status, e o dispatcher (Chunk 2c)
fará round-robin entre contas ativas.

Senha vai criptografada via Fernet (key em env `AJUS_FERNET_KEY`).

Status:
  offline           — nunca logou ou logout explícito
  logando           — runner está executando o flow de login
  aguardando_ip_code — AJUS pediu código de verificação de IP
  online            — sessão válida, pronta pra dispatch
  executando        — runner usando essa conta agora (lock)
  erro              — falha persistente; operador edita ou desativa

Revision ID: ajus003
Revises: ajus002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus003"
down_revision: Union[str, None] = "ajus002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ajus_session_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Rótulo amigável pro operador (ex.: "Conta MDR 1", "Robo BA").
        sa.Column("label", sa.String(length=64), nullable=False, unique=True),
        # Login técnico (visível). Senha criptografada (Fernet, base64 ASCII).
        sa.Column("login", sa.String(length=128), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        # Caminho relativo dentro do volume `/data/ajus-session/` onde fica
        # o storage_state.json dessa conta. Ex.: "1/storage_state.json".
        # Resolvido pelo session_service no momento de leitura/escrita.
        sa.Column(
            "storage_state_path", sa.String(length=255), nullable=True,
        ),
        # Estado atual — ver docstring do módulo.
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="offline",
            index=True,
        ),
        # Pendência de IP-code: quando AJUS pede, runner para o flow e
        # marca status='aguardando_ip_code'. Operador submete o código
        # via endpoint, que grava em `pending_ip_code` — runner consome
        # e limpa quando consegue completar o login.
        sa.Column(
            "pending_ip_code", sa.String(length=32), nullable=True,
        ),
        # Última mensagem de erro pra exibir na UI (ex.: senha inválida,
        # AJUS retornou 503, IP-code expirado).
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        # Última vez que o dispatcher escolheu essa conta — usado pro
        # tiebreaker round-robin (least-recently-used).
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # Conta pode ser desativada sem deletar (preserva histórico).
        # Dispatcher só pega ativas com status='online'.
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            index=True,
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
        sa.CheckConstraint(
            "status IN ('offline','logando','aguardando_ip_code',"
            "'online','executando','erro')",
            name="ck_ajus_session_accounts_status",
        ),
    )

    # Adiciona FK em ajus_classificacao_queue → conta usada no dispatch.
    # NULL enquanto pendente; preenchido quando dispatcher pega o item.
    # ondelete=SET NULL pra preservar histórico se conta for deletada.
    with op.batch_alter_table("ajus_classificacao_queue") as batch_op:
        batch_op.add_column(
            sa.Column(
                "dispatched_by_account_id",
                sa.Integer(),
                sa.ForeignKey(
                    "ajus_session_accounts.id", ondelete="SET NULL",
                ),
                nullable=True,
                index=True,
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("ajus_classificacao_queue") as batch_op:
        batch_op.drop_column("dispatched_by_account_id")
    op.drop_table("ajus_session_accounts")
