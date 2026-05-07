"""contestacao_existente: detecta contestacao ja apresentada na integra do intake

Adiciona colunas no `prazo_inicial_intakes` pra persistir a deteccao da
IA quando a integra ja contem uma contestacao apresentada (caso tipico:
reprocessamento de intake antigo, intake atrasado onde escritorio
anterior ja contestou, ou processo herdado).

Pareia com o BlocoContestacaoExistente do schema Pydantic
(`prazos_iniciais_schema.py`). Nao interfere em sugestoes de prazo nem
em patrocinio - so metadado pra revisao humana decidir se complementa,
refaz, ou confirma sem providencia.

Campos:
- contestacao_existe: bool, default false. True quando a IA detectou
  contestacao na integra.
- contestacao_apresentada_por_mdr: bool nullable. True se assinada por
  Marcos Delli (qualquer variacao). False se outro advogado. Null se
  nao foi possivel identificar (peca truncada).
- contestacao_apresentada_por_nome: nome do signatario.
- contestacao_apresentada_por_oab: OAB/UF NNNNN.
- contestacao_parte_representada: qual reu do polo passivo a peca
  defendeu (critico em multi-reus - contestacao do Banco Will nao
  conta como contestacao do Master).
- contestacao_data_apresentacao: data da peticao de contestacao.
- contestacao_generica: bool nullable. True quando boilerplate sem
  aderencia ao caso, false quando customizada, null quando indeterminado.
- contestacao_analise_qualidade: 1-3 frases descrevendo qualidade
  pro HITL.

Sem dataloss - todos os campos sao nullable (exceto o flag bool com
default false). Backfill automatico via server_default.

Revision ID: pin021
Revises: ajus008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "pin021"
down_revision: Union[str, None] = "ajus008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_existe",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_apresentada_por_mdr",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_apresentada_por_nome",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_apresentada_por_oab",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_parte_representada",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_data_apresentacao",
            sa.Date(),
            nullable=True,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_generica",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "prazo_inicial_intakes",
        sa.Column(
            "contestacao_analise_qualidade",
            sa.Text(),
            nullable=True,
        ),
    )

    # Indice parcial em (contestacao_existe, contestacao_apresentada_por_mdr)
    # pra suportar relatorios "intakes com contestacao MDR generica".
    op.create_index(
        "ix_prazo_inicial_intakes_contestacao_existe",
        "prazo_inicial_intakes",
        ["contestacao_existe"],
        unique=False,
        postgresql_where=sa.text("contestacao_existe IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prazo_inicial_intakes_contestacao_existe",
        table_name="prazo_inicial_intakes",
    )
    op.drop_column("prazo_inicial_intakes", "contestacao_analise_qualidade")
    op.drop_column("prazo_inicial_intakes", "contestacao_generica")
    op.drop_column("prazo_inicial_intakes", "contestacao_data_apresentacao")
    op.drop_column("prazo_inicial_intakes", "contestacao_parte_representada")
    op.drop_column("prazo_inicial_intakes", "contestacao_apresentada_por_oab")
    op.drop_column("prazo_inicial_intakes", "contestacao_apresentada_por_nome")
    op.drop_column("prazo_inicial_intakes", "contestacao_apresentada_por_mdr")
    op.drop_column("prazo_inicial_intakes", "contestacao_existe")
