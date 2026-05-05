"""adiciona tabelas de patrocinio e empresas vinculadas Master

Patrocínio é uma análise paralela à classificação de prazos: aplica-se
APENAS quando o polo passivo do processo contém alguma empresa vinculada
ao Banco Master (matriz/filiais ou empresas correlatas em liquidação
extrajudicial). Não interfere nas tarefas — só registra a decisão de
patrocínio (MDR Advocacia / Outro escritório / Condução interna) e
suspeita de devolução, com fluxo HITL próprio.

Estrutura:
- `master_vinculadas`: tabela de configuração editável das empresas
  vinculadas ao Master (CNPJs que disparam a análise). Seed inicial com
  17 empresas listadas pelo cliente.
- `prazo_inicial_patrocinio`: 1:1 com intake. Persiste decisão da IA +
  campos preenchidos + status de revisão pelo operador.

Revision ID: pin018
Revises: pin017
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "pin018"
down_revision: Union[str, None] = "pin017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed inicial das vinculadas Master (lista fornecida pelo cliente).
_SEED_VINCULADAS = [
    ("33.923.798/0001-00", "Banco Master S/A — Matriz (Em Liq. Extrajud.)", "RJ"),
    ("33.923.798/0002-83", "Banco Master S/A — Filial (Em Liq. Extrajud.)", "SP"),
    ("33.923.798/0005-26", "Banco Master S/A — Filial (Em Liq. Extrajud.)", "BA"),
    ("33.923.798/0006-07", "Banco Master S/A — Filial (Em Liq. Extrajud.)", "MG"),
    ("33.884.941/0001-94", "Banco Master Múltiplo S.A.", "SP"),
    ("09.526.594/0001-43", "Banco Master de Investimentos S.A. — Matriz", "SP"),
    ("09.526.594/0002-24", "Banco Master de Investimentos S.A. — Filial (Em Liq. Extrajud.)", "RS"),
    ("03.566.273/0001-96", "Master Patrimonial LTDA — Matriz (Em Liq. Extrajud.)", "RJ"),
    ("33.886.862/0001-12", "Master S.A. Corretora de Câmbio, TVM — Matriz (Em Liq. Extrajud.)", "RJ"),
    ("33.886.862/0002-01", "Master S.A. Corretora de Câmbio, TVM — Filial (Em Liq. Extrajud.)", "SP"),
    ("58.497.702/0001-02", "Banco Lestbank (Em Liq. Extrajud.)", "SP"),
    ("43.336.034/0001-64", "EFB Regimes Especiais de Empresas Ltda.", "SP"),
    ("49.642.083/0001-01", "JK031 Empreendimentos e Participações S.A.", None),
    ("45.335.919/0001-74", "Master Patrimonial II Ltda.", None),
    ("37.609.924/0001-08", "AKM Holding Ltda.", None),
    ("31.042.414/0001-07", "Suhic Investimentos e Participações Ltda.", None),
    ("18.334.105/0001-42", "Mettacard — Administradora de Cartões Ltda.", None),
]


def upgrade() -> None:
    op.create_table(
        "master_vinculadas",
        sa.Column("id", sa.Integer(), primary_key=True),
        # CNPJ canônico (com máscara). É a chave de matching contra o
        # polo passivo do intake — guardamos com pontuação pra UI bater
        # 1:1 com o que vem da automação externa / extração mecânica.
        sa.Column("cnpj", sa.String(length=18), nullable=False, unique=True, index=True),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("estado", sa.String(length=2), nullable=True),
        sa.Column(
            "ativo",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
    )

    # Seed inicial das vinculadas
    op.bulk_insert(
        sa.table(
            "master_vinculadas",
            sa.column("cnpj", sa.String),
            sa.column("nome", sa.String),
            sa.column("estado", sa.String),
            sa.column("ativo", sa.Boolean),
        ),
        [
            {"cnpj": cnpj, "nome": nome, "estado": estado, "ativo": True}
            for cnpj, nome, estado in _SEED_VINCULADAS
        ],
    )

    op.create_table(
        "prazo_inicial_patrocinio",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "intake_id",
            sa.Integer(),
            sa.ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        # MDR_ADVOCACIA / OUTRO_ESCRITORIO / CONDUCAO_INTERNA
        sa.Column("decisao", sa.String(length=32), nullable=False),
        sa.Column("outro_escritorio_nome", sa.String(length=255), nullable=True),
        sa.Column("outro_advogado_nome", sa.String(length=255), nullable=True),
        sa.Column("outro_advogado_oab", sa.String(length=32), nullable=True),
        sa.Column("outro_advogado_data_habilitacao", sa.Date(), nullable=True),
        sa.Column(
            "suspeita_devolucao",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            index=True,
        ),
        sa.Column("motivo_suspeita", sa.Text(), nullable=True),
        # CONSUMERISTA / CIVIL_PUBLICA / INQUERITO_ADMINISTRATIVO /
        # TRABALHISTA / OUTRO
        sa.Column("natureza_acao", sa.String(length=32), nullable=True),
        # Cadastro do polo passivo (capa) bate com o que a IA inferiu
        # da PI. Quando False, alerta operador pra checar.
        sa.Column(
            "polo_passivo_confirmado",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("polo_passivo_observacao", sa.Text(), nullable=True),
        sa.Column("confianca", sa.String(length=16), nullable=True),
        sa.Column("fundamentacao", sa.Text(), nullable=True),
        # Review status: pendente | aprovado | editado | rejeitado
        sa.Column(
            "review_status",
            sa.String(length=16),
            server_default="pendente",
            nullable=False,
            index=True,
        ),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_email", sa.String(length=255), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("prazo_inicial_patrocinio")
    op.drop_table("master_vinculadas")
