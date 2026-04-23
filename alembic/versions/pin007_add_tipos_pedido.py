"""adiciona prazo_inicial_tipos_pedido (46 tipos iniciais)

Tabela de dicionário com os tipos de pedido que a IA (Sonnet) extrai
da petição inicial para compor a análise de provisionamento/contingência.
Seed inicial de 40 tipos vindos da taxonomia exportada pelo MDR + 6
tipos adicionais específicos de polo passivo bancário (revisão
contratual, repetição de indébito simples, nulidade de cláusula,
suspensão de desconto em folha, recálculo de dívida, declaração de
inexigibilidade).

Revision ID: pin007
Revises: tpl004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pin007"
down_revision: Union[str, None] = "tpl004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED = [
    # (codigo, nome, naturezas_csv, display_order)
    # ─── 40 do Excel do MDR ─────────────────────────────────────────
    ("DECIMO_TERCEIRO", "13º Salário", "Trabalhista", 100),
    ("ADICIONAL_ASSIDUIDADE", "Adicional de Assiduidade", "Trabalhista", 100),
    ("ADICIONAL_INSALUBRIDADE", "Adicional de Insalubridade", "Trabalhista", 100),
    ("ADICIONAL_PENOSIDADE", "Adicional de Penosidade", "Trabalhista", 100),
    ("ADICIONAL_PERICULOSIDADE", "Adicional de Periculosidade", "Trabalhista", 100),
    ("ADICIONAL_TURNO", "Adicional de Turno", "Trabalhista", 100),
    ("ADICIONAL_NOTURNO", "Adicional Noturno", "Trabalhista", 100),
    ("ANTECIPACAO_TUTELA", "Antecipação de Tutela", "Ambiental;Cível;Constitucional;Penal;Previdenciária;Trabalhista;Tributária", 50),
    ("ANULACAO_REGISTRO", "Anulação de Registro", "Cível", 100),
    ("APOSENTADORIA_ESPECIAL", "Aposentadoria Especial", "Previdenciária", 100),
    ("APRESENTACAO_DOCUMENTOS", "Apresentação de Documentos", "Cível;Trabalhista", 100),
    ("ASSINATURA_CTPS", "Assinatura CTPS", "Trabalhista", 100),
    ("AUXILIO_DOENCA", "Auxílio Doença", "Previdenciária;Trabalhista", 100),
    ("AUXILIO_FUNERAL", "Auxílio Funeral", "Previdenciária;Trabalhista", 100),
    ("AUXILIO_MATERNIDADE", "Auxílio Maternidade", "Previdenciária;Trabalhista", 100),
    ("BAIXA_ORGAOS_PROTECAO_CREDITO", "Baixa nos Órgãos de Proteção ao Crédito", "Consumidor", 40),
    ("COMPLEMENTACAO_APOSENTADORIA", "Complementação de Aposentadoria", "Previdenciária;Trabalhista", 100),
    ("COMPLEMENTO_DEPOSITO_FGTS", "Complemento de Depósito do FGTS", "Trabalhista", 100),
    ("DANOS_MATERIAIS", "Danos Materiais", "Ambiental;Cível;Constitucional;Penal;Previdenciária;Trabalhista;Tributária", 10),
    ("DANOS_MORAIS", "Danos Morais", "Ambiental;Cível;Constitucional;Consumidor;Penal;Previdenciária;Trabalhista;Tributária", 10),
    ("DEPOSITO_FGTS", "Depósito de FGTS", "Trabalhista", 100),
    ("DEVOLUCAO_DESCONTO_INDEVIDO", "Devolução de Desconto Indevido", "Cível;Tributária", 30),
    ("DEVOLUCAO_VALORES_PAGOS", "Devolução de Valores Pagos", "Cível;Tributária", 30),
    ("DEVOLUCAO_EM_DOBRO", "Devolução em Dobro", "Cível;Tributária", 30),
    ("DIFERENCA_SALARIAL", "Diferença Salarial", "Trabalhista", 100),
    ("EXIBICAO_DOCUMENTOS", "Exibição de Documentos", "Administrativa;Cível;Consumidor;Trabalhista", 70),
    ("FALENCIA", "Falência", "Cível", 100),
    ("FERIAS", "Férias", "Trabalhista", 100),
    ("HONORARIO_SUCUMBENCIA", "Honorário de Sucumbência", "Cível;Trabalhista", 80),
    ("HONORARIOS", "Honorários", "Cível", 80),
    ("HONORARIOS_CONTRATUAIS", "Honorários Contratuais", "Cível", 80),
    ("HONORARIOS_SUCUMBENCIAIS", "Honorários Sucumbenciais", "Administrativa;Cível;Consumidor;Trabalhista", 80),
    ("INEXISTENCIA_DEBITO", "Inexistência de Débito", "Cível", 20),
    ("JUSTICA_GRATUITA", "Justiça Gratuita", "Administrativa;Cível;Consumidor;Trabalhista", 60),
    ("LIMINAR", "Liminar", "Ambiental;Cível;Constitucional;Penal;Previdenciária;Trabalhista;Tributária", 50),
    ("OBRIGACAO_FAZER", "Obrigação de Fazer", "Cível;Consumidor;Trabalhista", 40),
    ("PAGAMENTO_DIVIDA", "Pagamento de Dívida", "Cível;Trabalhista", 100),
    ("REPACTUACAO_DIVIDA", "Repactuação de Dívida", "Cível;Consumidor", 20),
    ("RETIRADA_CPF_ORGAOS_DEFESA", "Retirada do CPF de Órgãos de Defesa do Crédito", "Cível", 40),
    ("SERASA_LIMPA_NOME", "Serasa Limpa Nome", "Cível;Consumidor", 40),

    # ─── 6 extras bancários (polo passivo) ──────────────────────────
    ("REVISAO_CONTRATUAL", "Revisão Contratual", "Cível;Consumidor", 15),
    ("REPETICAO_INDEBITO_SIMPLES", "Repetição de Indébito Simples", "Cível;Tributária", 30),
    ("NULIDADE_CLAUSULA_CONTRATUAL", "Nulidade de Cláusula Contratual", "Cível;Consumidor", 20),
    ("SUSPENSAO_DESCONTO_FOLHA", "Suspensão de Desconto em Folha", "Cível;Consumidor;Previdenciária", 15),
    ("RECALCULO_DIVIDA", "Recálculo de Dívida", "Cível;Consumidor", 25),
    ("DECLARACAO_INEXIGIBILIDADE", "Declaração de Inexigibilidade", "Cível;Consumidor", 20),
]


def upgrade() -> None:
    op.create_table(
        "prazo_inicial_tipos_pedido",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("codigo", sa.String(), nullable=False, unique=True),
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("naturezas", sa.String(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="100"),
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # ATENÇÃO: NÃO criar índice explícito sobre 'codigo' — a coluna já
    # tem unique=True na definição da tabela, o que cria um índice único
    # implícito. Criar um 2º índice causa 'relation already exists' no
    # PostgreSQL e derruba a migration.
    op.create_index(
        "ix_prazo_inicial_tipos_pedido_is_active",
        "prazo_inicial_tipos_pedido",
        ["is_active"],
    )

    # Seed dos 46 tipos.  Usamos bulk_insert pra eficiência e porque o
    # Alembic gerencia dialect-awareness (ex.: server_default da coluna
    # is_active = true vai ser usado automaticamente; aqui setamos só
    # o subconjunto relevante).
    tipos_pedido = sa.table(
        "prazo_inicial_tipos_pedido",
        sa.column("codigo", sa.String),
        sa.column("nome", sa.String),
        sa.column("naturezas", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        tipos_pedido,
        [
            {
                "codigo": codigo,
                "nome": nome,
                "naturezas": naturezas,
                "display_order": display_order,
                "is_active": True,
            }
            for codigo, nome, naturezas, display_order in SEED
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prazo_inicial_tipos_pedido_is_active",
        table_name="prazo_inicial_tipos_pedido",
    )
    op.drop_table("prazo_inicial_tipos_pedido")
