"""Adiciona tabelas do módulo AJUS (códigos de andamento + fila de inserção).

Onda inicial do módulo AJUS:
- `ajus_cod_andamento`: catálogo dos códigos de andamento que serão
  enviados via POST /inserir-prazos da AJUS. Templates configuráveis
  (situacao, offsets de data, texto da informação) determinam o payload
  que sai pra cada item enfileirado. Operador cadastra/edita pela UI.
- `ajus_andamento_queue`: fila de andamentos a inserir na AJUS. Cada
  intake de prazos iniciais que entra com status RECEBIDO gera um item
  aqui automaticamente, usando o cod_andamento marcado como `is_default`.
  Disparo é manual (operador acumula e clica "Enviar lote").

Não tem tabela de settings — credenciais (bearer JWT, cliente, login,
senha, base URL) ficam em variáveis de ambiente lidas via
`app.core.config.settings`.

Revision ID: ajus001
Revises: pin013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus001"
down_revision: Union[str, None] = "pin013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Catálogo de códigos de andamento ─────────────────────────────
    # Cada código carrega um TEMPLATE: o que vai pro payload AJUS quando
    # esse código for usado pra enfileirar um andamento. Os offsets das
    # datas são em dias úteis a partir do dia em que o intake foi
    # recebido (data_evento). Diversos códigos podem coexistir; a UI
    # escolhe pelo `is_default` no enfileiramento automático.
    op.create_table(
        "ajus_cod_andamento",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("codigo", sa.String(length=64), nullable=False, unique=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        # Template do payload AJUS pra esse código
        sa.Column(
            "situacao",
            sa.String(length=1),
            nullable=False,
            server_default="A",
        ),
        sa.Column(
            "dias_agendamento_offset_uteis",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "dias_fatal_offset_uteis",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        # Template de texto livre da `informacao` — aceita placeholders
        # {cnj}, {data_recebimento} (preenchidos no momento do
        # enfileiramento). String simples, sem HTML.
        sa.Column(
            "informacao_template",
            sa.Text(),
            nullable=False,
            server_default="Andamento — processo {cnj}.",
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
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
            "situacao IN ('A','C')", name="ck_ajus_cod_andamento_situacao",
        ),
    )
    # Apenas um is_default por vez — partial unique index.
    op.create_index(
        "ux_ajus_cod_andamento_default",
        "ajus_cod_andamento",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )

    # ── Fila de andamentos a inserir na AJUS ────────────────────────
    # 1 intake → 0 ou 1 item de fila (idempotente via unique em
    # intake_id). O PDF é COPIADO da habilitação pra `pdf_path` próprio
    # da fila (storage `ajus_pdfs/...`) pra sobreviver à rotina de
    # cleanup do prazos iniciais. Cópia é apagada quando AJUS retorna
    # sucesso (sucesso = `cod_informacao_judicial` preenchido).
    op.create_table(
        "ajus_andamento_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "intake_id",
            sa.Integer(),
            sa.ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("cnj_number", sa.String(length=25), nullable=False, index=True),
        sa.Column(
            "cod_andamento_id",
            sa.Integer(),
            sa.ForeignKey("ajus_cod_andamento.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        # Snapshot dos campos do payload no momento do enfileiramento.
        # Snapshotamos pra que mudanças posteriores no template do
        # cod_andamento NÃO afetem itens já enfileirados (auditoria).
        sa.Column("situacao", sa.String(length=1), nullable=False),
        sa.Column("data_evento", sa.Date(), nullable=False),
        sa.Column("data_agendamento", sa.Date(), nullable=False),
        sa.Column("data_fatal", sa.Date(), nullable=False),
        sa.Column("hora_agendamento", sa.Time(), nullable=True),
        sa.Column("informacao", sa.Text(), nullable=False),
        # Caminho RELATIVO da cópia do PDF (relativo a AJUS_STORAGE_PATH).
        # Ex.: "2026/04/28/abc.pdf". NULL se intake veio sem PDF.
        sa.Column("pdf_path", sa.String(length=512), nullable=True),
        # Status de processamento na fila:
        #   pendente — enfileirado, aguardando disparo
        #   enviando — POST em curso (lock soft)
        #   sucesso  — AJUS retornou inserido=true; cod_informacao_judicial preenchido
        #   erro     — AJUS retornou inserido=false (msg em error_message) OU exception
        #   cancelado — operador cancelou manualmente
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pendente",
            index=True,
        ),
        sa.Column(
            "cod_informacao_judicial",
            sa.String(length=64),
            nullable=True,
            unique=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "situacao IN ('A','C')", name="ck_ajus_queue_situacao",
        ),
        sa.CheckConstraint(
            "status IN ('pendente','enviando','sucesso','erro','cancelado')",
            name="ck_ajus_queue_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("ajus_andamento_queue")
    op.drop_index(
        "ux_ajus_cod_andamento_default",
        table_name="ajus_cod_andamento",
    )
    op.drop_table("ajus_cod_andamento")
